#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot.
# Probe the filesystem instead of spawning a Python interpreter: under the
# 8-round parallel sweep, per-boot `python3 -c "import flask"` costs a full
# interpreter startup (~0.25s CPU) on each of hundreds of boots and widens the
# CPU-contention window in which the runner's health poll can time out.
flask_found=""
for p in /usr/local/lib/python3*/dist-packages/flask/__init__.py \
         /usr/local/lib/python3*/site-packages/flask/__init__.py \
         /usr/lib/python3*/dist-packages/flask/__init__.py; do
  if [ -f "$p" ]; then
    flask_found=1
    break
  fi
done
if [ -z "$flask_found" ]; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
