#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. Use find_spec (no
# package init) instead of a full import so the dependency probe costs ~0.1s,
# not ~1s, shaving redundant CPU off every per-test boot under 8x contention.
if ! python3 -c "import importlib.util as u, sys; sys.exit(0 if (u.find_spec('flask') and u.find_spec('waitress')) else 1)" 2>/dev/null; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
