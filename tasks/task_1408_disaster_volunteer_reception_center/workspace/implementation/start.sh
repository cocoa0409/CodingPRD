#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Boot cost matters: start.sh is re-run before every per-test reboot (8 sweep
# rounds concurrently on a shared host), and the runner's readiness poll gives
# each restart a bounded window. Spawn as few interpreters as possible: verify
# deps once (marker file), then exec the app directly.
MARKER=".deps_installed"
if [ ! -f "$MARKER" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt --break-system-packages
  fi
  touch "$MARKER"
fi
exec python3 app.py
