#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); an unconditional pip install, or even a per-boot
# `python3 -c "import flask"` probe, spawns a second interpreter per restart
# and under 8x parallel load that extra spawn measurably widens the boot
# distribution tail, surfacing as flaky "could not be restarted" timeouts.
# A stamp file makes the steady-state check a single stat(2) syscall.
STAMP=".deps_installed"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  python3 -m pip install -q -r requirements.txt
  touch "$STAMP"
fi
exec python3 app.py
