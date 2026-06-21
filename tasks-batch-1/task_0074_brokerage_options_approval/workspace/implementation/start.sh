#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt && touch .deps_installed
fi
exec python3 app.py
