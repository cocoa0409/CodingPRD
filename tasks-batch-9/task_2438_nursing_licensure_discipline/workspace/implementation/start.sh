#!/usr/bin/env bash
# Launch the Nursing Licensure and Discipline Management System API.
# Binds 0.0.0.0 on ${PORT:-10000} and runs in the foreground.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 \
    || python3 -m pip install --quiet --disable-pip-version-check --break-system-packages -r requirements.txt
fi

exec python3 app.py
