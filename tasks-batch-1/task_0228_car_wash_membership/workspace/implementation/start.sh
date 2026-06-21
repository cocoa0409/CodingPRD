#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before every per-test reboot (8 rounds concurrently). To
# minimise boot-time contention we (a) install deps only once, gated by a
# sentinel file rather than an extra Python subprocess on every reboot, and
# (b) exec the single server interpreter so no shell process lingers.
SENTINEL=".deps_installed"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
