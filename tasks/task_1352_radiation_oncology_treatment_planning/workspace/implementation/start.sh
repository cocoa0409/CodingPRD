#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only once — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); a per-boot pip install (or even a per-boot
# `python3 -c "import flask"` probe) pays a full interpreter start on every
# restart, which under sweep load pushes boots past the restart-poll window
# and surfaces as flaky "could not be restarted" timeouts.
# The marker file caches dependency presence; it is environment setup only —
# no entity data is ever persisted (the store is in-memory per process).
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_installed
fi
exec python3 app.py
