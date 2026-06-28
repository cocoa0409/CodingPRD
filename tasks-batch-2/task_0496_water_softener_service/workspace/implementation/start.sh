#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot (8 rounds run concurrently,
# ~73 reboots each). Any extra interpreter spawn here is paid hundreds of times
# under 8x CPU contention and shows up as flaky "could not be restarted"
# timeouts. So we cache the dependency check with a sentinel file: the flask
# import probe (a whole extra python3 process) runs only on the very first boot;
# every subsequent boot skips straight to `exec python3 app.py`.
SENTINEL=".deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL"
fi
exec python3 app.py
