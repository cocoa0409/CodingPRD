#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install dependencies only when they are missing, so a per-test server restart
# costs nothing and the server answers well inside the 60-second budget.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PORT="${PORT:-10000}"
exec python3 app.py
