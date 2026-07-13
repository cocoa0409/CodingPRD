#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependencies are resolved at most once and recorded with a marker file.
# start.sh is re-run before EVERY per-test reboot, and 8 rounds reboot in
# lockstep; spawning an extra `python3 -c "import flask"` interpreter (or an
# unconditional pip install) on every reboot creates an 8x Python-startup +
# flask-import CPU storm that can push one round's boot past the runner's 15s
# readiness window ("could not be restarted"). The marker keeps the steady-state
# reboot a single `exec python3 app.py`.
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
exec python3 app.py
