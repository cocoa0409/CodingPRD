#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently, plus co-tenant load on the host); any per-boot
# subprocess (pip, python probe) inflates boot time and risks the runner's
# 15s health-poll window ("could not be restarted"). A sentinel file keeps
# the steady-state boot to a single `exec python3 app.py` with zero probes.
if [ ! -f .deps_installed ]; then
  if python3 -c "import flask" >/dev/null 2>&1; then
    touch .deps_installed
  else
    python3 -m pip install -q -r requirements.txt
    touch .deps_installed
  fi
fi
exec python3 app.py
