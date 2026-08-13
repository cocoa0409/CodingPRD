#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Deps are installed once and stamped; per-test reboots skip the extra Python
# interpreter spawn so boot stays fast under concurrent restart storms.
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
exec python3 app.py
