#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (many rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. find_spec answers
# without importing the package, so the guard costs a bare interpreter boot
# instead of a full flask import on every restart.
if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)"; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
