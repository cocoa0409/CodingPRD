#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency guard via stamp file: start.sh is re-run before every per-test
# reboot (8 rounds concurrently), and a `python3 -c "import flask"` probe costs
# a full interpreter+Flask import (~0.7s) per boot — enough to push boots past
# the runner's restart poll under host load. First boot verifies the import
# (installing only if missing) and stamps .deps_ok; later boots cost a stat().
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
exec python3 app.py
