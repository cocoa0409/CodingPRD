#!/usr/bin/env bash
# Launches the Retail Media Network API in the foreground on $PORT.
# Every invocation is a brand new process, so all state is wiped.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

PY="${PYTHON:-python3}"

if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi

exec "$PY" app.py
