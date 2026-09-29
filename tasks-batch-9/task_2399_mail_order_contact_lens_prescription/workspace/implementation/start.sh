#!/usr/bin/env bash
# Launch the mail-order contact lens prescription API.
# Boots a fresh process with empty in-memory state on every invocation.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1

# Cheap dependency probe: find_spec avoids paying for a full flask import here.
if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec python3 app.py
