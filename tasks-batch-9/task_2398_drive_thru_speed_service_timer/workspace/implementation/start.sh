#!/usr/bin/env bash
# Launch the Drive-Thru Speed-Of-Service API in the foreground.
# The harness re-runs this script for every test, so the dependency install is
# guarded and the server always boots with a completely empty in-memory store.
set -e

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 \
    || python3 -m pip install --quiet --break-system-packages --disable-pip-version-check flask
fi

exec python3 app.py
