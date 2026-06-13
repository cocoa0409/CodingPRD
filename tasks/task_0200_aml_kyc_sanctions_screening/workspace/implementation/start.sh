#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot, and the sweep launches 8
# rounds concurrently — so each boot competes for CPU with ~7 others. Keep the
# critical path to "spawn interpreter + exec app" with no extra interpreter
# spawns: a full `python3 -c "import flask"` probe on every restart roughly
# doubles per-boot cost under contention and is what tips a boot past the
# runner's readiness window ("could not be restarted").
#
# Resolve dependencies exactly once per checkout via a filesystem sentinel;
# every subsequent restart skips straight to exec.
SENTINEL=".deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL"
fi
exec python3 app.py
