#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing - start.sh is re-run before every per-test reboot
# and an unconditional pip install would slow startup past the restart window.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
