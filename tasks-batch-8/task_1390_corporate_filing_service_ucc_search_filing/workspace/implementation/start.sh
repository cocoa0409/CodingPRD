#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-invoked before every per-test
# reboot (potentially concurrently); an unconditional pip install on every boot
# causes contention and flaky restart timeouts. A sentinel file avoids paying
# a full python interpreter spawn (`python3 -c "import flask"`) on every boot.
if [ ! -f .deps_installed ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_installed
fi
exec python3 app.py
