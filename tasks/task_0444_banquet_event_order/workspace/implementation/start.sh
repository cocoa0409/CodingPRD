#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-invoked before EVERY per-test server reboot, and the 8 stability
# rounds run concurrently, so boot latency sits on the critical path. Gate the
# one-time dependency install behind a sentinel kept OUTSIDE the implementation
# tree (the impl dir must stay write-free / state-free), keyed to this Python so
# steady-state restarts exec straight into the app with no probe subprocess.
SENTINEL="${TMPDIR:-/tmp}/.beo_deps_ok_$(python3 -c 'import sys;print(sys.prefix.replace("/","_"))')"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL" 2>/dev/null || true
fi
exec python3 app.py
