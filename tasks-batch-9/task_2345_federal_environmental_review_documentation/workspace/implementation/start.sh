#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before every per-test reboot and several rounds run
# concurrently, so boot cost matters. app.py installs its own dependency only if
# the import actually fails, which keeps the common path to a single interpreter
# launch instead of paying for a separate `import flask` probe every boot.
exec python3 app.py
