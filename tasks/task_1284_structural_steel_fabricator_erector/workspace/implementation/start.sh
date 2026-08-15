#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently). Probe with find_spec (no flask import): a full
# `python3 -c "import flask"` doubles per-boot interpreter+import cost, and
# under sweep contention pushes boots past the runner's restart-poll window.
if ! python3 -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec("flask") else 1)'; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
