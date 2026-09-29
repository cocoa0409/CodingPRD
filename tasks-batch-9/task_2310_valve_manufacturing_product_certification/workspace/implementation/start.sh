#!/usr/bin/env bash
# Launcher for the valve manufacturing / product certification API.
# Boots a fresh in-memory process on every invocation.
set -e

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || \
    python3 -m pip install --quiet --break-system-packages --disable-pip-version-check flask
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
