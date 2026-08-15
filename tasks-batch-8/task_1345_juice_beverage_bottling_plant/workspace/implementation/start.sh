#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before every per-test reboot (8 rounds concurrently), so
# boot latency directly feeds the runner's 15s restart-poll window. Keep the
# boot path to a single interpreter spawn: probe for flask via find_spec (no
# package import) and install only if genuinely absent.
if ! python3 -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('flask') else 1)"; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
