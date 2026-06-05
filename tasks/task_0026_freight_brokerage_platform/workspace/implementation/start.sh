#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Skip pip install when both deps already importable. The per-test-server
# isolation restarts the server before every test; if 8 parallel sweeps each
# pip-install at every restart they race on $HOME/Library/Python/3.9/bin
# entry-point script rewrites. Once installed, the import is enough.
if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
  # First install needs serialization across concurrent sweeps.
  exec 9>/tmp/prd_bench_freight_0026_pip.lock
  flock 9
  if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  flock -u 9
fi
exec python3 app.py
