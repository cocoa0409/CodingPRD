#!/bin/bash
set -e
cd "$(dirname "$0")"
pip install -q --no-input flask >/dev/null 2>&1 || pip install --no-input flask
export PYTHONUNBUFFERED=1
export PORT="${PORT:-10000}"
exec python3 -m server
