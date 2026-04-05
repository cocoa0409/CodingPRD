from huggingface_hub import snapshot_download, login
import os
from loguru import logger

PROJ_ID = 'AGI-Eval/PRDbench'
BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data/hf_datasets')

def main():
    login(os.getenv('HF_TOKEN'))

    logger.info(f'Downloading {PROJ_ID} to {BASE_DIR}')

    local_dir = os.path.join(BASE_DIR, PROJ_ID.split('/')[-1])
    os.makedirs(local_dir, exist_ok=True)

    snapshot_download(
        repo_id=PROJ_ID, 
        repo_type='dataset',
        local_dir=local_dir
    )

    logger.success(f'Downloaded {PROJ_ID} to {local_dir}')

if __name__ == '__main__':
    main()