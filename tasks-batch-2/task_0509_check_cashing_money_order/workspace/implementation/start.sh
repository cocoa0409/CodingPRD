#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before every per-test reboot (under an 8-round concurrent
# sweep that is ~664 reboots total). Dependency provisioning must therefore be
# as close to free as possible after the first install: a per-reboot
# `python3 -c "import flask"` probe pays a full interpreter-startup + Flask
# import every time and, under peak concurrent CPU load, that extra cost is
# exactly what pushes an occasional boot past the runner's fixed 15s restart
# window and surfaces as a spurious "could not be restarted".
#
# Instead, gate the install on a cheap filesystem sentinel written after the
# first successful install. The probe (and any pip work) then runs at most once
# per environment; every subsequent reboot skips straight to exec.
SENTINEL=".deps_installed"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL"
fi
exec python3 app.py
