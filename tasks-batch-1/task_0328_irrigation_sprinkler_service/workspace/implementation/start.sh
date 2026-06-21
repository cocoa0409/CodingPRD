#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-invoked before EVERY per-test reboot (8 rounds run concurrently),
# so the steady-state path must be as cheap as possible. We gate the (one-time)
# dependency install behind a filesystem sentinel in $TMPDIR: a plain `[ -f ]`
# test spawns no extra Python interpreter, whereas the previous
# `python3 -c "import flask"` probe launched a second interpreter on every single
# boot — pure CPU contention under the 8x concurrent sweep that occasionally
# pushed boot past the runner's 15s restart window ("could not be restarted"
# flakes). The sentinel lives outside the source tree and only records that the
# interpreter already satisfies the deps; it carries no application state, so the
# in-memory store still starts empty on every boot.
SENTINEL="${TMPDIR:-/tmp}/.prd0328_deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
