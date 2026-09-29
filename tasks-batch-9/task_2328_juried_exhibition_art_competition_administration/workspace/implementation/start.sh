#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); an unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
# The presence probe is a pure-shell directory check first: spawning a second
# interpreter only to `import flask` doubles boot time on a loaded host, and
# every per-test reboot pays it. The interpreter probe is still the fallback,
# so an unusual install layout is never mistaken for a missing dependency.
have_flask=""
for d in "${HOME:-/root}"/.local/lib/python3.*/site-packages \
         /usr/lib/python3/dist-packages \
         /usr/lib/python3.*/site-packages \
         /usr/local/lib/python3.*/site-packages; do
  if [ -d "$d/flask" ]; then have_flask=1; break; fi
done
if [ -z "$have_flask" ] && ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt || \
    python3 -m pip install -q --break-system-packages -r requirements.txt
fi
exec python3 app.py
