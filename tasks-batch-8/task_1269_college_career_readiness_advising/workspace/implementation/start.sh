#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before every per-test reboot (8 rounds concurrently), so
# keep the boot path minimal: flask is preinstalled (requirements.txt), and an
# extra dependency-check process per boot measurably widens the vulnerable
# window in which the harness's 15s restart poll can time out under load.
# Fallback for a bare environment: install once, marked by a sentinel file.
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt && touch .deps_installed
fi
export PYTHONDONTWRITEBYTECODE=1
exec python3 app.py
