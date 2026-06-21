#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot (71 tests x 8 concurrent
# rounds). The hot path must be as cheap as possible: an extra `python3 -c
# import ...` probe on every boot doubles the interpreter-start cost under 8x
# CPU contention and pushes some boots past the runner's 15s restart window
# (surfacing as a spurious "could not be restarted"). So we gate the one-time
# dependency install behind a cheap filesystem sentinel and otherwise go
# straight to `exec`.
SENTINEL=".deps_installed"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
