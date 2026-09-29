#!/usr/bin/env bash
# Boots the API from a fresh process with an empty in-memory store.
set -e

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

# The harness relaunches this script before every test, so only install when
# the dependency is actually missing.
if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1
fi

exec python3 app.py
