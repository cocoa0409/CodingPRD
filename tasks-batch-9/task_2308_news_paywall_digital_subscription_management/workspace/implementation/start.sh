#!/usr/bin/env bash
# Launch the paywall API in the foreground on $PORT (default 8080), binding 0.0.0.0.
# Every invocation is a brand-new process with empty in-memory storage.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8080}"
export PORT
export PYTHONUNBUFFERED=1

# Detect Flask without spawning an interpreter: probing with `python3 -c "import
# flask"` costs a full interpreter start on every boot, which dominates start-up
# latency. Bytecode caching is deliberately left enabled for the same reason.
shopt -s nullglob
flask_found=0
for candidate in \
  "$HOME"/.local/lib/python3*/site-packages/flask \
  /usr/lib/python3*/site-packages/flask \
  /usr/lib/python3/dist-packages/flask \
  /usr/local/lib/python3*/site-packages/flask
do
  if [ -d "$candidate" ]; then
    flask_found=1
    break
  fi
done
shopt -u nullglob

if [ "$flask_found" -eq 0 ]; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec python3 app.py
