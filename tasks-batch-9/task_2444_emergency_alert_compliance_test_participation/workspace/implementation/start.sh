#!/usr/bin/env bash
# Launch the EAS Compliance API in the FOREGROUND on $PORT (default 10000).
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PY="${PYTHON:-python3}"

# Guarded dependency install: only runs when Flask is genuinely missing.
if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || "$PY" -m pip install --quiet --break-system-packages -r requirements.txt
fi

exec "$PY" app.py
