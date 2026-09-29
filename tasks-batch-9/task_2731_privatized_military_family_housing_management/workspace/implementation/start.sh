#!/usr/bin/env bash
# Boots the API from a clean process; all state is in-memory and starts empty.
set -e

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
exec python3 app.py
