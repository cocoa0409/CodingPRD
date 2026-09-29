#!/usr/bin/env bash
# Launcher contract: `bash start.sh` boots the API on $PORT (default 10000),
# bound to 0.0.0.0, in the foreground. Storage is in-memory only, so every
# invocation starts from an empty store.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask \
    >/dev/null 2>&1 \
    || python3 -m pip install --quiet --disable-pip-version-check \
         --break-system-packages flask >/dev/null 2>&1 \
    || python3 -m pip install --quiet --user flask >/dev/null 2>&1
fi

exec python3 app.py
