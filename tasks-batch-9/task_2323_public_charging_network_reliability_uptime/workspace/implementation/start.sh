#!/usr/bin/env bash
# Launch the API.  A fresh process means empty in-memory stores and a reset
# logical clock, which is what the per-test-server harness relies on.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Launched as a module rather than `python3 app.py` so the process command
# line does not collide with unrelated process-name sweeps on shared CI
# hosts; behaviour is identical (__name__ is "__main__" either way).
exec python3 -m app
