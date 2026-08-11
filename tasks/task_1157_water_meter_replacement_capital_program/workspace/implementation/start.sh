#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install (or even a probing
# `python3 -c "import flask"`, which costs a full interpreter boot per
# restart) causes boot-time contention and flaky "could not be restarted"
# timeouts. A sentinel file keeps the steady-state check to one stat().
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_installed
fi
exec python3 app.py
