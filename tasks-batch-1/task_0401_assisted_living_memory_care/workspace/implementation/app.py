"""Assisted Living & Memory Care API — Flask entry point.

In-memory storage only. The store starts EMPTY on every boot; nothing is
seeded. All preconditions are built by tests through the API surface.
"""
import os
import socket as _socket

# ---------------------------------------------------------------------------
# Fast-boot guard: neutralize a macOS reverse-DNS (PTR) stall.
#
# Werkzeug's dev server calls socket.getfqdn(host) during server_bind purely to
# compose its "Running on http://..." startup banner. On some hosts (notably
# macOS) getfqdn("0.0.0.0") blocks ~5s on a reverse-DNS lookup that times out,
# because the unspecified address has no hostname. Under per-test-server
# isolation the server reboots before EVERY test, so that 5s stall is paid
# hundreds of times and pushes boot past the restart-poll window, surfacing as
# spurious setup timeouts / "could not be restarted".
#
# We only fast-path the unspecified-address cases; named addresses fall through
# to the real resolver unchanged. getfqdn's result is never used for anything
# but the cosmetic log line, so no behavior is affected. This is the same patch
# the runner injects via PYTHONPATH; applying it here makes boot fast even when
# that injection is absent.
# ---------------------------------------------------------------------------
_real_getfqdn = _socket.getfqdn
_UNSPECIFIED = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}


def _fast_getfqdn(name=""):
    if name in _UNSPECIFIED:
        return "localhost"
    return _real_getfqdn(name)


_socket.getfqdn = _fast_getfqdn

from flask import Flask

import errors
import response
from routes import register_routes

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.after_request
def _no_keep_alive(resp):
    # Force a fresh TCP connection per request. The test harness reuses a single
    # requests.Session (keep-alive) across the per-test-server reboots; if we let
    # the connection persist, the pooled socket points at the just-killed server
    # process after a restart and the next request blocks on a dead connection
    # until the pytest setup timeout fires. Closing the connection each response
    # makes every request reconnect, so a restart is always picked up cleanly.
    resp.headers["Connection"] = "close"
    return resp


@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    # Unknown route — generic not found shaped as an error envelope.
    return response.error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return response.error("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return response.error(exc.error_id, exc.message, exc.http_status)
    return response.error("ERR_INTERNAL", str(exc), 500)


register_routes(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
