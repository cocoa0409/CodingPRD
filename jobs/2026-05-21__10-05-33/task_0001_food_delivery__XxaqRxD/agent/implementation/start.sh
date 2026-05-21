#!/bin/bash
set -e
cd "$(dirname "$0")"
pip install -q -r requirements.txt
export PYTHONUNBUFFERED=1
export PORT="${PORT:-10000}"
exec python3 app.py
