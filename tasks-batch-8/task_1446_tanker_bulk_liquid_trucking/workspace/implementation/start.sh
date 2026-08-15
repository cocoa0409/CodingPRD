#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. The sentinel file
# keeps the dependency check to a shell builtin after the first successful
# boot instead of spawning a Python interpreter per boot.
if [ ! -f .deps_installed ] || [ requirements.txt -nt .deps_installed ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_installed
fi
exec python3 app.py
