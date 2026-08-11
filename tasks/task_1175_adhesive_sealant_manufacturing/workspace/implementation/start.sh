#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# The per-test runner kills the previous listener on this port before launching
# us, but under parallel sweep load that kill can race/time out, leaving the
# port bound — the new server would then die on EADDRINUSE and the runner's
# readiness poll would expire ("could not be restarted"). Defensively free our
# own port first: kill any leftover LISTEN socket (lsof with -n -P avoids DNS
# stalls) and wait until a bind probe succeeds, up to ~10s.
python3 - "${PORT:-10000}" <<'PYEOF'
import socket, subprocess, sys, time

port = int(sys.argv[1])
deadline = time.monotonic() + 10.0
while True:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
    except OSError:
        s.close()
        subprocess.run(
            f"lsof -n -P -ti:{port} -sTCP:LISTEN | xargs -r kill -9",
            shell=True, capture_output=True,
        )
        if time.monotonic() > deadline:
            break
        time.sleep(0.25)
        continue
    s.close()
    break
PYEOF

exec python3 app.py
