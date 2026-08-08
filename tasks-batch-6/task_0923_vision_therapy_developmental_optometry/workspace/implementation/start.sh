#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# The harness re-invokes start.sh before every test (per-test-server isolation),
# so the dependency install must be a cheap no-op once Flask is importable.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PYTHONDONTWRITEBYTECODE=1
exec python3 app.py
