import os, json
from datetime import timedelta
from typing import Annotated, Optional
import openai
from fastapi import FastAPI, HTTPException, UploadFile,  Header, Depends, Form, File
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from config import *
from models import Token, User, ChatMessages, FineTuningSpecs
from finetuning.openai import upload_training_file, fine_tune_openai_model
from finetuning.validation import validate_data_format, validate_messages
from dependencies import *
from load_models.model_list import models
from load_models.model_loader import load_models
from inference.text_generator import generate_text_phi1_5, create_prompt, generate_text_pipeline

app = FastAPI()

loaded_models = load_models(models)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

load_dotenv()  # Load environment variables from .env file
SECRET_KEY = os.getenv("SECRET_KEY")

async def get_secret_key(authorization: str = Header(...)):
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Secret Key")
    secret_key = authorization[len(prefix):]

    if secret_key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Secret Key")
    return secret_key

@app.post("/token", response_model=Token)
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    user = authenticate_user(fake_users_db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=User)
async def read_users_me(current_user: Annotated[User, Depends(get_current_active_user)]):
    return current_user

@app.get("/")
async def root(current_user: User = Depends(get_current_active_user)):
    if current_user:
        return {"message": "Hello World"}
    return {"message": "Unauthorized"}

@app.post("/api/chat/opensourcemodel")
async def chat(
    chat_messages: ChatMessages,
    secret_key: str = Depends(get_secret_key
)):
    model_name = chat_messages.selected_model
    chat_history = chat_messages.chat_history
    # Ensure that 'model_name' is a valid key in 'loaded_models'
    if model_name not in loaded_models.keys():
        raise HTTPException(status_code=400, detail="Invalid model name")

    model = loaded_models[model_name]['model']
    tokenizer = loaded_models[model_name]['tokenizer']
    try:
        if model_name == "microsoft/phi-1_5":
            question = chat_messages.question        
            generated_text = generate_text_phi1_5(model, tokenizer, question)
        else:
            prompt = create_prompt(models, model_name, chat_history)
            generated_text = generate_text_pipeline(model, tokenizer, prompt)

        return {
            "success": True, 
            "message": generated_text
        }
    except Exception as e:
             raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/finetuning/openai")
async def finetune(
    file: UploadFile = File(...),
    fine_tuning_model: str = Form(..., alias='finetuning'),
    suffix: str = Optional[str],
    n_epochs: int = Form(..., alias='epochs'),
    secret_key: str = Depends(get_secret_key)
):
    file_content = await file.read()
    file_str = file_content.decode('utf-8')
    file_list = [json.loads(line) for line in file_str.splitlines() if line]
   
    data_format_errors = validate_data_format(file_list)
    messages_errors = validate_messages(file_list)
    
    if not messages_errors and not data_format_errors:
        try:
            openai.api_key = os.getenv("OPENAI_API_KEY")
            
            file_submit_result = await upload_training_file(file_content)
            file_id = file_submit_result["id"]

            res = await fine_tune_openai_model(file_id, fine_tuning_model, suffix, n_epochs)
            fine_tuning_job_id = res["id"]

            return {
                "success": True, 
                "id": fine_tuning_job_id,  
                "message": "Your request has been successfully sent to OpenAI"}
        except Exception as e:
             raise HTTPException(detail=str(e))
    else:
        errors = {
            "data_format": validate_data_format,
            "messages": validate_messages
        }
        return {
            "success": False,
            "id": fine_tuning_job_id, 
            "error": errors
        }  

@app.post("/api/finetuning/peft")
async def finetune( 
    file: UploadFile = File(...),
    fine_tuning_model: str = Form(..., alias='finetuning'),
    epochs: int = Form(...),
    batch_size: Optional[int] = Form(None, alias='batchSize'),
    learning_rate_multiplier: Optional[float] = Form(None, alias='learningRateMultiplier'),
    prompt_loss_weight: Optional[float] = Form(None, alias='promptLossWeight'),
    secret_key: str = Depends(get_secret_key)
):
    content = await file.read()
    specs = FineTuningSpecs(
        fine_tuning_model=fine_tuning_model,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate_multiplier=learning_rate_multiplier,
        prompt_loss_weight=prompt_loss_weight
    )
    # process and validate the uploaded file/data
    # run fine-tuning work (DeepSpeed ZeRO, LoRA, Flash Attention)
    # pass
