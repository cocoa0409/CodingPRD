#!/usr/bin/env bash
# Launch the hearing-care API. Fresh process, fresh in-memory state every time.
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
# The image ships bare python:3.12-slim, so install the declared dependency the
# first time this boots; later per-test reboots find flask already importable.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
