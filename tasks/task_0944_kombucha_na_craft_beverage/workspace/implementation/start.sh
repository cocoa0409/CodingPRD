#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing.  start.sh is re-invoked before every per-test
# reboot; an unconditional pip install would contend badly under the
# concurrent stability sweep and show up as "could not be restarted".
if ! python3 -c "import flask, werkzeug" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PORT="${PORT:-10000}"
exec python3 app.py
