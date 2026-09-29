#!/bin/bash
# Launch the Equestrian Show Management API.  Every invocation starts a fresh
# process with a completely empty in-memory store.
set -e

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Install Flask only when it is missing, so re-launches (one per test under
# --isolation per-test-server) stay fast.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q --disable-pip-version-check -r requirements.txt \
    || python3 -m pip install -q --disable-pip-version-check --break-system-packages -r requirements.txt
fi

exec python3 app.py
