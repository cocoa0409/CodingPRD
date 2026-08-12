#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. The presence check
# uses find_spec (~30 ms) instead of importing flask (~600 ms) to keep the
# per-test reboot window small under parallel load.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)"; then
  python3 -m pip install -q -r requirements.txt \
    || python3 -m pip install -q --break-system-packages -r requirements.txt
fi
exec python3 app.py
