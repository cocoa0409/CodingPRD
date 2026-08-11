#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install deps only on first boot (sentinel) — start.sh is re-run before every
# per-test reboot, and a full `import flask` probe doubles boot time.
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_installed
fi
exec python3 app.py
