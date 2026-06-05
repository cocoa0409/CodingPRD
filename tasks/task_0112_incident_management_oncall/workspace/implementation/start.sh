#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency bootstrap is gated by a filesystem sentinel so the common warm-boot
# path spawns exactly ONE python process (the server). start.sh is re-run before
# every per-test reboot, and during the concurrent 8-round stability sweep that
# is ~hundreds of reboots competing for the host's CPUs. An unconditional
# `python3 -c "import flask"` guard would spawn a second cold interpreter on
# every boot, doubling cold-start contention and producing flaky
# "could not be restarted" timeouts. Once deps are confirmed present we drop the
# sentinel and skip the check entirely on subsequent boots. (.deps_ok is a build
# artifact, not entity state — it holds no resource data.)
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
# Pre-compile bytecode once so reboots skip .py -> .pyc compilation. Best-effort.
if [ ! -f .compiled_ok ]; then
  python3 -m compileall -q . >/dev/null 2>&1 || true
  touch .compiled_ok
fi
exec python3 app.py
