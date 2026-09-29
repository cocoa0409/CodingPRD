#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

PY="${PYTHON:-python3}"

if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install -q -r requirements.txt >/dev/null 2>&1 \
    || "$PY" -m pip install -q --break-system-packages -r requirements.txt >/dev/null 2>&1
fi

exec "$PY" app.py
