#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Install only when missing - start.sh is re-run before every per-test reboot.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
