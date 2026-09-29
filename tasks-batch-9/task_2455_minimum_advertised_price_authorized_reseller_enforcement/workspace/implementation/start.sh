#!/usr/bin/env bash
# Launch the MAP Authorized Reseller Enforcement API in the foreground.
# Every invocation starts a brand-new process with completely empty in-memory state.
set -euo pipefail

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || python3 -m pip install --quiet --break-system-packages -r requirements.txt
fi

export PORT="${PORT:-10000}"
exec python3 app.py
