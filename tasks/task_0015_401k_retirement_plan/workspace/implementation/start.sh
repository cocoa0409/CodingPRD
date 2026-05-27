#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install -q -r requirements.txt
exec python3 app.py
