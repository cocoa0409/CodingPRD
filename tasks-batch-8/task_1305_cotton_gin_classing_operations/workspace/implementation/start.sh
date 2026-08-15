#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency bootstrap, paid exactly once per workspace. start.sh is re-invoked
# before every per-test reboot (many concurrent rounds on a shared host); even
# a bare `python3 -c "import flask"` probe costs a full interpreter spawn per
# boot, which under load spikes past the runner's restart-poll window. The
# sentinel records "deps verified/installed" so steady-state boots go straight
# to exec. The pip fallback covers PEP 668 externally-managed environments.
if [ ! -f .deps_installed ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt || \
      python3 -m pip install -q --break-system-packages -r requirements.txt
  fi
  touch .deps_installed
fi
exec python3 app.py
