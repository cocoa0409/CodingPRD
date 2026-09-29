#!/usr/bin/env bash
# Launcher for the IRF Admission & Compliance API.
# Installs dependencies only when they are missing, then runs the server in the
# foreground on 0.0.0.0:$PORT (default 10000).
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || python3 -m pip install --quiet --disable-pip-version-check --break-system-packages -r requirements.txt
fi

exec python3 app.py
