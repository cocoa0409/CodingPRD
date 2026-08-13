#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Deps fast path: start.sh is re-run before EVERY per-test server reboot
# (8 sweep rounds concurrently). Spawning a Python interpreter (or worse,
# pip) here costs hundreds of ms idle and can stall for many seconds under
# host contention, pushing the boot past the runner's restart-poll window
# and surfacing as a spurious "could not be restarted". Install once, mark
# with .deps_ok, and later boots pay only a stat(2).
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
exec python3 app.py
