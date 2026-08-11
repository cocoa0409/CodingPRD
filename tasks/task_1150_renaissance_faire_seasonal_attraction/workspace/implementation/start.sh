#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently). A sentinel file records a completed dependency
# install so repeat boots skip the ~200ms `python3 -c "import flask"` spawn,
# cutting boot latency and reducing restart-storm contention.
_SENTINEL=".deps_installed"
if [ ! -f "$_SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$_SENTINEL"
fi
exec python3 app.py
