"""Roommate Expense Split API — Flask entry point.

In-memory storage only; no seeding at startup. Reads $PORT, binds 0.0.0.0, foreground.
"""
import os
import socket as _socket

# ---------------------------------------------------------------------------
# Boot-latency hardening (must run BEFORE Flask/Werkzeug import).
#
# On macOS, socket.getfqdn("0.0.0.0") blocks ~5s on a reverse-DNS (PTR) lookup
# that times out. Werkzeug's dev server calls getfqdn(host) during server_bind
# purely to compose its "Running on http://..." startup banner. Under
# per-test-server isolation the server is restarted before EVERY test, and the
# 8-round concurrent stability sweep pays that 5s stall on every boot — which
# can push a boot past the runner's restart-poll window and surface as a
# spurious "could not be restarted" failure. Patching getfqdn here makes the
# server immune regardless of how it is launched; only the cosmetic banner
# hostname is affected.
# ---------------------------------------------------------------------------
_real_getfqdn = _socket.getfqdn
_UNSPECIFIED_ADDRS = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}


def _fast_getfqdn(name=""):
    if name in _UNSPECIFIED_ADDRS:
        return "localhost"
    return _real_getfqdn(name)


_socket.getfqdn = _fast_getfqdn

from flask import Flask

import response
from errors import ApiError
from routes.profiles import bp as profiles_bp
from routes.listings import bp as listings_bp
from routes.match_requests import bp as match_requests_bp
from routes.households import bp as households_bp
from routes.memberships import bp as memberships_bp
from routes.bills import bp as bills_bp
from routes.expenses import bp as expenses_bp
from routes.settlements import bp as settlements_bp
from routes.reminders import bp as reminders_bp
from routes.disputes import bp as disputes_bp
from routes.testdriving import bp as testdriving_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        profiles_bp, listings_bp, match_requests_bp, households_bp, memberships_bp,
        bills_bp, expenses_bp, settlements_bp, reminders_bp, disputes_bp, testdriving_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return response.error("ERR_VALIDATION", "Bad request.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return response.error(e.error_id, e.message, e.http_status)
        return response.error("ERR_VALIDATION", "Unexpected error: %s" % e, 422)

    return app


app = create_app()


if __name__ == "__main__":
    import logging
    import time

    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "10000"))
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # Bind with a short retry loop. Under per-test-server isolation the runner
    # SIGKILLs the previous server and immediately re-invokes start.sh; the old
    # socket can still be in TIME_WAIT/closing when the new process binds. A
    # transient "Address already in use" must not crash the boot.
    srv = None
    deadline = time.time() + 12.0
    last_err = None
    while time.time() < deadline:
        try:
            srv = make_server("0.0.0.0", port, app, threaded=True)
            break
        except OSError as e:
            last_err = e
            time.sleep(0.1)
    if srv is None:
        raise SystemExit(f"Could not bind 0.0.0.0:{port}: {last_err}")
    srv.serve_forever()
