#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

$PYTHON -m pip install -q --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 || \
  $PYTHON -m pip install -q flask >/dev/null 2>&1 || true

export PORT="${PORT:-10000}"
exec $PYTHON app.py
