#!/usr/bin/env bash
# Boot the eligibility API. A fresh process means a completely empty store.
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-10000}"
export PYTHONDONTWRITEBYTECODE=1
python3 -c 'import flask' 2>/dev/null || python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
exec python3 app.py
