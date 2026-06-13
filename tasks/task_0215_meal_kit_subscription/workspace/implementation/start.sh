#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before every per-test reboot (8 rounds concurrently), so
# boot must be fast and free of avoidable subprocesses. A marker file records
# that deps are present; once written, subsequent boots skip the dependency
# probe entirely (no extra `python3 -c import flask` interpreter per boot),
# avoiding boot-time CPU contention and flaky "could not be restarted" timeouts.
DEPS_MARKER=".deps_ok"
if [ ! -f "$DEPS_MARKER" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  # Pre-compile our modules to .pyc once, so every subsequent per-test boot
  # imports from the bytecode cache instead of recompiling source — cutting
  # boot latency and its variance under heavy concurrent restarts.
  python3 -m compileall -q . >/dev/null 2>&1 || true
  : > "$DEPS_MARKER"
fi
exec python3 app.py
