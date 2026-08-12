#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install dependencies only when needed — start.sh is re-run before every
# per-test reboot (8 rounds concurrently), so an unconditional pip install
# causes boot-time contention. After the first successful check a marker file
# lets later boots skip the interpreter probe entirely.
MARKER=.deps_installed
if [ ! -f "$MARKER" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$MARKER"
fi
exec python3 app.py
