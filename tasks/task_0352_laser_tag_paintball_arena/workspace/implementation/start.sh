#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot, and the stability sweep runs
# 8 rounds concurrently. Spawning an extra `python3 -c "import flask"` interpreter
# on every boot doubles process-spawn pressure at each test boundary and can push
# a boot past the runner's 15s restart-poll window ("could not be restarted").
#
# So gate the dependency check on a one-time filesystem sentinel: only the very
# first boot pays the import-check (and pip install when genuinely missing); every
# subsequent boot does zero extra subprocess work and goes straight to exec.
SENTINEL=".deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL"
fi
exec python3 app.py
