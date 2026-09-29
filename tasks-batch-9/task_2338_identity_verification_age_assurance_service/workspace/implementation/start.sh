#!/usr/bin/env bash
# Boot the API on $PORT (default 10000).
#
# The harness restarts this script before every test and reclaims the port by
# SIGKILLing whatever is LISTENing on it.  On a heavily loaded host that reclaim
# can fail (it shells out to `lsof` under a 5s timeout), leaving the previous
# listener alive so a plain `python3 app.py` dies instantly on "Address already
# in use".  So: keep one wrapper per port, recorded in a pidfile that doubles as
# an ownership token, and retry the bind instead of giving up on the first
# collision.
cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
PIDFILE="${TMPDIR:-/tmp}/prd_bench_wrapper_${PORT}.pid"

port_bound() {
    (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") >/dev/null 2>&1
}

# Take ownership of the port: stop the previous wrapper for this port (and its
# server child) so it cannot respawn and race us for the bind.
prev=$(cat "$PIDFILE" 2>/dev/null)
if [ -n "$prev" ] && [ "$prev" != "$$" ] && [ -r "/proc/$prev/cmdline" ] &&
   tr -d '\0' < "/proc/$prev/cmdline" | grep -q 'start\.sh' &&
   [ "$(readlink -f "/proc/$prev/cwd" 2>/dev/null)" = "$PWD" ]; then
    pkill -9 -P "$prev" >/dev/null 2>&1
    kill -9 "$prev" >/dev/null 2>&1
fi
echo $$ > "$PIDFILE"

owner() { [ "$(cat "$PIDFILE" 2>/dev/null)" = "$$" ]; }

# The image ships bare python:3.12-slim, so install the declared dependency
# before the bind loop; later per-test reboots find flask already importable.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

attempt=0
while [ "$attempt" -lt 40 ]; do
    attempt=$((attempt + 1))
    # A newer wrapper owns this port now: stand down rather than fight over it.
    owner || exit 0

    # Wait for the port before paying the interpreter's import cost, so a doomed
    # bind never burns a boot's worth of the harness poll window.
    wait_i=0
    while port_bound; do
        wait_i=$((wait_i + 1))
        owner || exit 0
        [ "$wait_i" -gt 150 ] && break
        # Cheap reclaim first (the stale listener is usually our own child);
        # the expensive port scan only if the listener outlives it.
        [ "$wait_i" = 5 ] || [ "$wait_i" = 40 ] && timeout 3 fuser -k -n tcp "$PORT" >/dev/null 2>&1
        sleep 0.2
    done

    python3 app.py
    rc=$?

    owner || exit 0
    # The port is free, so the server really did stop (the harness killed it, or
    # it crashed).  Nothing to retry: exit and let the harness decide.
    port_bound || exit "$rc"
    # Still bound => this bind lost a race with a stale listener; loop and retry.
done

exit 1
