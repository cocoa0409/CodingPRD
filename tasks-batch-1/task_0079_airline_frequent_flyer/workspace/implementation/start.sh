#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Create the venv and install dependencies only once. Under per-test-server
# isolation start.sh is re-invoked before every test; re-running pip each time
# overloads the host and delays HTTP readiness past the boot window. Guard with
# a sentinel so subsequent restarts skip straight to launching the app.
if [ ! -f .venv/.deps_installed ]; then
  python3 -m venv .venv >/dev/null 2>&1 || true
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -q -r requirements.txt >/dev/null 2>&1 || pip install -q -r requirements.txt
  touch .venv/.deps_installed
else
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export PORT="${PORT:-10000}"
exec python app.py
