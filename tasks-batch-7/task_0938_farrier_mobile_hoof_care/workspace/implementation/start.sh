#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Probe with find_spec rather than importing flask: importing costs ~250ms and
# start.sh is re-run before EVERY per-test reboot.  pip only runs when a
# dependency is genuinely absent.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') and importlib.util.find_spec('werkzeug') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
