#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot (hundreds of times, with up to
# 8 sweep rounds concurrent). Each extra interpreter spawn here multiplies the
# fork/startup pressure that pushes a boot past the runner's 15s restart-poll
# window and surfaces as a spurious "could not be restarted".
#
# So: do the dependency install AT MOST ONCE, gated by a cheap filesystem
# sentinel (a `[ -f ]` test, not a Python `import` subprocess). On the first ever
# boot the sentinel is absent -> verify/install deps, then drop the marker. Every
# subsequent reboot sees the marker and goes straight to `exec python3 app.py`
# with no precheck interpreter at all.
SENTINEL=".deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL"
fi
exec python3 app.py
