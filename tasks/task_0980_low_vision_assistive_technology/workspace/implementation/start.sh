#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Deps are installed once and marked with a sentinel file — start.sh is re-run
# before every per-test reboot (8 rounds concurrently), and even a
# `python3 -c "import flask"` probe costs a full interpreter boot each time,
# which under parallel load produced flaky "could not be restarted" timeouts.
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_installed
fi
exec python3 app.py
