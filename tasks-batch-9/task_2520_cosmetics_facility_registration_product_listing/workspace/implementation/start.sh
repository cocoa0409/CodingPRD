#!/usr/bin/env bash
# Boot the API in the foreground on $PORT (default 8000), binding 0.0.0.0.
# All state is in process memory, so every invocation starts from a clean slate.
set -euo pipefail

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

export PORT="${PORT:-8000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
