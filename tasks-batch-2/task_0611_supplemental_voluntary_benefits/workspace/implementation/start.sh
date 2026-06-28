#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency install is the slow, contention-prone part of boot. Under
# per-test-server isolation start.sh re-runs before EVERY test, and the 8-round
# concurrent sweep multiplies that by 8 — so any avoidable per-boot work
# (spawning an extra `python3 -c "import flask"` interpreter each time) directly
# eats into the runner's 15s restart window and shows up as flaky "could not be
# restarted" failures. We install at most once and gate it behind a marker file
# so the steady-state boot is a single exec with no extra subprocess spawn.
MARKER=".deps_installed"
if [ ! -f "$MARKER" ]; then
  if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  # Only mark deps satisfied once both imports actually resolve, so a partial
  # install never gets cached as "done".
  if python3 -c "import flask, waitress" >/dev/null 2>&1; then
    touch "$MARKER"
  fi
fi
exec python3 app.py
