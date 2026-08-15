#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently, possibly alongside other pipelines on the same host);
# unconditional pip install here causes boot-time contention and flaky
# "could not be restarted" timeouts. The marker file avoids paying a second
# Python interpreter spawn (~0.3s idle, much worse under load) on every reboot
# once dependencies have been verified once on this machine.
MARKER=".deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
  if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt || \
      python3 -m pip install -q --user --break-system-packages -r requirements.txt
  fi
  touch "$MARKER"
fi
exec python3 app.py
