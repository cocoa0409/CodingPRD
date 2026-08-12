#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency guard. start.sh is re-run before every per-test server reboot
# (hundreds of times per stability sweep). A full "import flask" probe pays
# Flask's import cost on every boot, adding CPU load under the concurrent sweep;
# find_spec only *locates* the module (no import), so this probe stays cheap.
# pip is only invoked when flask is genuinely absent.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)"; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
