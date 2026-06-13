#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install dependencies once. start.sh is re-run before every per-test reboot (8
# rounds concurrently), so the hot path must avoid spawning an extra Python
# interpreter just to probe for flask: a sentinel file records that deps are
# installed, collapsing each restart to a single `exec python3 app.py`.
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_installed
fi
exec python3 app.py
