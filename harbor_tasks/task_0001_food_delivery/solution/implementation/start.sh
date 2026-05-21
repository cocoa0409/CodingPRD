#!/bin/bash
set -e
cd "$(dirname "$0")"
pip install -q -r requirements.txt
exec python app.py
