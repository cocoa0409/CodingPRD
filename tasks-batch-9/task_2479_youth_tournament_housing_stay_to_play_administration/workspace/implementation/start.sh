#!/usr/bin/env bash
# Launch the housing API in the foreground on $PORT (default 10000), bound to
# 0.0.0.0.  The harness kills and relaunches this script before every test, so
# the dependency install is guarded and the process must never fork.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 || true
fi

exec python3 app.py
