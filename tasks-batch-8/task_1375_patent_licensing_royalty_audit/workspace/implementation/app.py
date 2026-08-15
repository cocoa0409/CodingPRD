"""Patent Licensing & Royalty Audit API -- Flask entry point.

Boot ordering matters under the benchmark's per-test-server isolation: the
runner SIGKILLs whatever listens on $PORT and immediately re-invokes
start.sh, then polls for readiness. While the port is unbound, any outbound
localhost connection on a shared host can be assigned $PORT as its ephemeral
source port; when that client closes, the port sits in TIME-WAIT for ~60s and
our bind fails with EADDRINUSE (SO_REUSEADDR does not override a TIME-WAIT
socket created without it), which surfaces as a spurious "could not be
restarted" test error. To shrink that free-port window to a minimum, this
module binds the listen socket FIRST — before importing Flask — and only then
loads the application stack and serves on the pre-bound socket.
"""
import errno
import importlib.util
import os
import socket
import subprocess
import sys
import time

PORT = int(os.environ.get("PORT", "10000"))
_HERE = os.path.dirname(os.path.abspath(__file__))


def _ensure_dependencies():
    """Install requirements only when Flask is genuinely missing.

    find_spec does not execute the module, so the common path costs ~0ms;
    the slow `pip install` runs only on the first boot of a fresh host.
    """
    if importlib.util.find_spec("flask") is None:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-q",
            "-r", os.path.join(_HERE, "requirements.txt"),
        ])


def _bind_with_retry(port, attempts=120, interval=0.1):
    """Bind 0.0.0.0:port, retrying briefly on EADDRINUSE.

    The retry covers the previous server instance whose socket release may
    lag its SIGKILL by a few milliseconds, and any transient connection that
    grabbed the port in the restart gap and closes promptly.
    """
    last_err = None
    for _ in range(attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            s.listen(128)
            s.set_inheritable(True)
            return s
        except OSError as e:
            s.close()
            last_err = e
            if e.errno != errno.EADDRINUSE:
                raise
            time.sleep(interval)
    raise last_err


# Hold the port as early as possible; everything below happens with the port
# already owned by this process.
_listen_sock = _bind_with_retry(PORT)
_ensure_dependencies()

from flask import Flask  # noqa: E402

import errors  # noqa: E402
import response  # noqa: E402
from routes import (agreements, audits, clock, disputes, distributions,  # noqa: E402
                    findings, licensees, milestones, reports, sublicenses)

app = Flask(__name__)

for bp in (licensees.bp, agreements.bp, milestones.bp, sublicenses.bp,
           reports.bp, audits.bp, findings.bp, disputes.bp,
           distributions.bp, clock.bp):
    app.register_blueprint(bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return response.error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return response.error_response("ERR_VALIDATION", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return response.error_response("ERR_VALIDATION", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return response.error_response(e.error_id, e.message, e.http_status)
    return response.error_response("ERR_VALIDATION", str(e), 500)


if __name__ == "__main__":
    # Serve on the socket bound at module load (werkzeug's fd path performs
    # no bind of its own). ThreadedWSGIServer matches Flask's app.run
    # defaults: threaded=True with HTTP/1.1 keep-alive.
    from werkzeug.serving import ThreadedWSGIServer

    srv = ThreadedWSGIServer(
        "0.0.0.0", PORT, app,
        fd=_listen_sock.fileno(),
    )
    srv.serve_forever()
