#!/usr/bin/env bash
# Launcher contract: boots a fresh, empty, in-memory server in the foreground.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || "$PYTHON" -m pip install --quiet --break-system-packages -r requirements.txt
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
exec "$PYTHON" app.py
