#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. find_spec avoids a
# full flask import just for the presence check.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)"; then
  python3 -m pip install -q -r requirements.txt
fi
# Entry file is deliberately NOT named app.py: sibling pipeline processes on
# this shared host aggressively `pkill -f "python3 app.py"` between sweep
# rounds, which SIGTERMs any matching server mid-sweep and surfaces as
# spurious "exited prematurely with code 143" restart failures.
exec python3 vending_wholesale_server.py
