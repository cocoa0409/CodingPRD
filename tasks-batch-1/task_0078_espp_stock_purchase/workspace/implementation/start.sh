#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

python3 -m pip install -q -r requirements.txt

exec python3 app.py
