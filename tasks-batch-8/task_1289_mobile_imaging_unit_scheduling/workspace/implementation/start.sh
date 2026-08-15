#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (concurrently across rounds); unconditional pip install here causes boot-time
# contention and flaky restart timeouts. The presence check uses find_spec so
# the guard does not pay a full flask import on every boot.
if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') is not None else 1)"; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
