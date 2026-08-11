#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (concurrently during the stability sweep); an unconditional pip install here
# causes boot-time contention and flaky "could not be restarted" timeouts.
# The sentinel file keeps the check at zero interpreter cost after first boot.
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_installed
fi
exec python3 app.py
