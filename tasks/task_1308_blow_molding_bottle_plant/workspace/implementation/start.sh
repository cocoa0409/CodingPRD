#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. Probe with
# find_spec (no flask import) so a steady-state boot never pays a second
# full flask import before exec'ing the server.
if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') is not None else 1)"; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
