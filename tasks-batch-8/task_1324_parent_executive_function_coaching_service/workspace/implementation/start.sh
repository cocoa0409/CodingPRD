#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); an unconditional `python3 -c "import flask"` check
# doubles the Python interpreter boot cost per restart and, under parallel
# load, pushes boot past the runner's restart-poll window. The stamp file is
# build tooling only — it holds no entity state.
STAMP=".deps_installed"
if [ ! -f "$STAMP" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  python3 -m compileall -q . >/dev/null 2>&1 || true
  touch "$STAMP"
fi
exec python3 app.py
