#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Deps are pre-provisioned in this environment; verify once and record a
# sentinel. start.sh is re-invoked before every per-test reboot (8 concurrent
# rounds), and spawning a second Python interpreter just to probe for flask on
# every boot roughly doubles boot cost, widening the window in which a slow
# boot trips the runner's restart poll.
if [ ! -f .deps_installed ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt \
      || python3 -m pip install -q -r requirements.txt --break-system-packages \
      || true
  fi
  touch .deps_installed
fi
exec python3 app.py
