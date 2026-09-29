#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); an unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 || \
    python3 -m pip install -q --break-system-packages -r requirements.txt >/dev/null 2>&1 || true
fi
exec python3 app.py
