#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot, with 8 rounds running
# concurrently. Anything on the hot path here multiplies into boot-time CPU
# contention and flaky "could not be restarted" timeouts. The dependency check
# is therefore gated behind a sentinel so the common reboot path is a bare
# `exec python3 app.py` with no extra interpreter spawn or pip invocation.
# Sentinel lives in /tmp (not in the implementation dir) so no application
# state or build artifact is persisted alongside the code across reboots.
SENTINEL="/tmp/.prdbench_deps_ok_task0657"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
