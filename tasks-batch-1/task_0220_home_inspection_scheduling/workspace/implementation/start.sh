#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot (8 rounds run concurrently), so
# the hot path must do the absolute minimum work and bind the socket as fast as
# possible — otherwise boot latency under ~8x CPU/memory load can exceed the
# runner's 15s restart-poll window and surface as a flaky "could not be restarted".
#
# Dependency install is gated behind a one-time sentinel so the common (already
# installed) path never spawns an extra Python interpreter just to probe imports;
# the only process started on the hot path is the server itself.
SENTINEL=".deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL"
fi
exec python3 app.py
