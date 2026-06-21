#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
#
# A sentinel file records that deps are present so subsequent reboots skip the
# extra `python3 -c "import flask"` interpreter spawn entirely. Spawning a full
# Python process to import Flask on every one of (rounds x tests) reboots is
# pure boot-time contention under the 8-round concurrent sweep; the sentinel
# collapses it to one check per workspace.
SENTINEL=".deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
