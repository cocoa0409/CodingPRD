#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-invoked before EVERY per-test reboot, and the 8-round sweep runs
# 8 such reboot streams concurrently. To keep the hot path lean and avoid boot-time
# contention, dependency installation is gated behind a sentinel: the FIRST boot
# verifies/installs deps and drops a marker; every later boot skips straight to the
# server (no extra Python probe spawn, no pip). The marker is a build artifact only —
# all business/entity state remains in-memory and is wiped on every reboot.
MARKER=".deps_ok"
if [ ! -f "$MARKER" ]; then
  if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$MARKER"
fi
exec python3 app.py
