#!/usr/bin/env bash
# Launches the API in the foreground on $PORT (default 10000), binding 0.0.0.0.
# A fresh process starts with an entirely empty in-memory store.
set -e

cd "$(dirname "$0")"

# Dependency probe: locate Flask without importing it, so the launcher does not
# pay the cost of a full Flask import twice on every boot.
if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PORT="${PORT:-10000}"
exec python3 app.py
