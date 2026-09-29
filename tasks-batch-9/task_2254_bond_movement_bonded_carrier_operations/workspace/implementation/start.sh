#!/usr/bin/env bash
# Launch the In-Bond Movement API in the foreground on $PORT (default 10000).
set -e

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PY="${PYTHON:-python3}"

# Install Flask only when it is not importable already, so a warm environment
# boots instantly and a cold one still works.
if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || "$PY" -m pip install --quiet --disable-pip-version-check --break-system-packages -r requirements.txt
fi

exec "$PY" app.py
