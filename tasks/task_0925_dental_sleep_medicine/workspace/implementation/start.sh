#!/usr/bin/env bash
# Foreground launcher.  The harness re-invokes this before every single test
# (--isolation per-test-server), so the dependency install is guarded and the
# probe below is a cheap find_spec rather than a full framework import.
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 || python3 -m pip install -q -r requirements.txt
fi

# Fail fast and loudly if the app itself cannot be imported, rather than
# handing the harness a socket that never opens.
python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('app') else 1)"

export PORT="${PORT:-10000}"
exec python3 app.py
