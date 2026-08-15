#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before every per-test reboot (8 rounds concurrently).
# Keep the boot path minimal: flask is already installed in the environment;
# even a conditional `python3 -c "import flask"` probe pays a full interpreter
# startup per reboot and, under parallel sweep load, pushes boots past the
# runner's restart-poll window ("could not be restarted").
exec python3 app.py
