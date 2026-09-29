#!/usr/bin/env bash
# Boot the API from a fresh process. Storage is in-memory, so every launch
# starts from an empty store.
set -euo pipefail

cd "$(dirname "$0")"

# Cheap presence probe: locate the distribution without paying for a full
# `import flask` in a throwaway interpreter (the boot path runs once per test
# under per-test-server isolation, so the saved seconds matter).
if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PYTHONUNBUFFERED=1
export PORT="${PORT:-10000}"

exec python3 app.py
