#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing -- start.sh is re-run before every per-test reboot.
# find_spec avoids paying a full flask import in the check process on every boot.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)"; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
