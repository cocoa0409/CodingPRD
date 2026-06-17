#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependencies are installed exactly once, guarded by a filesystem sentinel
# (a build artifact, not entity state — application data lives only in memory
# and is wiped on every reboot). The runner re-invokes start.sh before every
# per-test reboot across concurrent rounds; spawning a second Python
# interpreter on each boot just to probe imports doubles per-restart startup
# cost and, under CPU saturation, can push a boot past the runner's restart
# poll window ("could not be restarted"). The sentinel skips both the probe
# and the install on the hot path, so the steady-state boot is a single
# `exec python3 app.py`.
SENTINEL=".deps_installed"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL"
fi
exec python3 app.py
