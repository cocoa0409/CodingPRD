#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-invoked before every per-test
# reboot (8 stability rounds concurrently); an unconditional pip install on
# every boot causes boot-time contention and flaky restart timeouts.
# find_spec locates flask without paying a full interpreter+flask import,
# keeping boot latency (and exposure to the restart poll window) minimal.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)"; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
