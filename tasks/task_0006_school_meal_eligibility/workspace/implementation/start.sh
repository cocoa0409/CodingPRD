#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Skip pip install if Flask is already importable — speeds up per-test-server
# restarts dramatically and avoids spurious BadStatusLine from a slow boot.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
