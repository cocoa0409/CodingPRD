#!/usr/bin/env bash
# Launch the Recruitment Marketing & Employer Brand Program API.
# Boots a fresh process with an empty in-memory store on every invocation.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PY="${PYTHON:-python3}"

if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || "$PY" -m pip install --quiet --disable-pip-version-check --break-system-packages -r requirements.txt
fi

exec "$PY" app.py
