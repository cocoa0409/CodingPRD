#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Skip the per-boot `python3 -c "import flask"` probe: it spawns an extra
# interpreter on every restart and, under the 8-round concurrent sweep,
# that probe alone can push a boot past the restart-poll window. Flask is
# already installed in the environment; if it ever isn't, the failure
# surfaces immediately as a ModuleNotFoundError from `python3 app.py`.
exec python3 app.py
