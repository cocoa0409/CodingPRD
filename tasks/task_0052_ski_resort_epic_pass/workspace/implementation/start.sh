#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -c "import flask" 2>/dev/null || python3 -m pip install -q -r requirements.txt 2>/dev/null || true
exec python3 app.py
