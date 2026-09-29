#!/usr/bin/env bash
# Launch the Concussion Protocol API in the foreground on $PORT (default 10000).
set -euo pipefail

cd "$(dirname "$0")"

# Cheap availability probe (find_spec does not execute the package) so that a
# relaunch on an already-provisioned host costs almost nothing.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 \
    || python3 -m pip install -q --break-system-packages -r requirements.txt >/dev/null 2>&1
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1

exec python3 app.py
