#!/bin/bash
set -e
cd "$(dirname "$0")"
pip3 install --quiet -r requirements.txt 2>/dev/null || pip install --quiet -r requirements.txt
export PORT="${PORT:-10000}"
exec python3 -u app.py
