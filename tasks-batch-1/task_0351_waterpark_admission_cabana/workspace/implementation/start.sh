#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependencies are installed once and a sentinel is dropped. start.sh is re-run
# before every per-test reboot (8 rounds concurrently), so the hot path must avoid
# spawning an extra Python interpreter just to probe for flask — that doubles
# process-spawn pressure under 8x load and drives flaky "could not be restarted"
# boot-timeout failures. The sentinel check is a cheap filesystem test instead.
SENTINEL=".deps_installed"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
