#!/usr/bin/env bash
# Launches the Warehouse Receipt & Commodity Collateral Administration API.
# State is in-memory only, so every invocation starts from an empty store.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PY="${PYTHON:-python3}"

if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    >/dev/null 2>&1 || true
fi

exec "$PY" grain_receipt_service.py
