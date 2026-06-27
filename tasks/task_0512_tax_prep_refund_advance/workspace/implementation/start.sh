#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot (74 tests x 8 concurrent
# rounds). Spawning a `python3 -c "import flask"` probe on every boot is pure
# CPU contention that can push the 15s restart window over the edge under load
# ("could not be restarted" flakiness). Use a one-time marker so the dependency
# check/install runs only on a fresh environment, then go straight to exec.
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
exec python3 app.py
