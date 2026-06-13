#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot, and the evaluator runs 8
# rounds concurrently — so the reboot hot path must spawn as few processes as
# possible. A filesystem sentinel records that deps are present, so steady-state
# reboots skip the extra `python3 -c "import flask"` interpreter launch (and the
# unconditional pip install) entirely, leaving a single `exec python3 app.py`.
# This minimizes per-reboot process-spawn contention that otherwise inflates
# boot latency under the phase-locked 8-round herd and trips the runner's
# 15s readiness poll ("could not be restarted").
SENTINEL=".deps_ready"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL"
fi
exec python3 app.py
