#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. A sentinel file keeps
# even the import probe off the hot path once deps are known-good.
if [ ! -f .deps_ok ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_ok
fi
exec python3 app.py
