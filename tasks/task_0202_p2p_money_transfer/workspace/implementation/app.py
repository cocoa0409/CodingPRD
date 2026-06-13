"""P2P Money Transfer API — Flask entry point.

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
# per-test-server isolation the server is restarted before EVERY test, and
# under the 8-round concurrent stability sweep that 5s stall — paid on every
# boot — can push a boot past the runner's 15s restart-poll window and surface
# as a spurious "could not be restarted" failure.
#
# The runner ships a PYTHONPATH-injected sitecustomize that patches this, but we
# do not depend on that landing: patching here makes the server immune to the
# stall regardless of how it is launched. Only the cosmetic banner hostname is
# affected; the server still binds 0.0.0.0 and serves identical responses.
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
from routes.accounts import bp as accounts_bp
from routes.funding_sources import bp as funding_sources_bp
from routes.recipient_verifications import bp as recipient_verifications_bp
from routes.transfers import bp as transfers_bp
from routes.money_requests import bp as money_requests_bp
from routes.split_requests import bp as split_requests_bp
from routes.risk_holds import bp as risk_holds_bp
from routes.disputes import bp as disputes_bp, rev_bp as reversals_bp
from routes.withdrawals import bp as withdrawals_bp
from routes.testdriving import bp as testdriving_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (accounts_bp, funding_sources_bp, recipient_verifications_bp,
               transfers_bp, money_requests_bp, split_requests_bp, risk_holds_bp,
               disputes_bp, reversals_bp, withdrawals_bp, testdriving_bp):
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
        return response.error("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # never leak a 500 in an unexpected envelope; surface as a generic 400-ish.
        if isinstance(e, ApiError):
            return response.error(e.error_id, e.message, e.http_status)
        return response.error("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    import logging
    import time

    from werkzeug.serving import make_server

    port = int(os.environ.get("PORT", "10000"))
    # Quiet the Werkzeug dev-server banner/request log: under per-test-server
    # isolation the server boots hundreds of times across the concurrent sweep,
    # and the banner work + per-request logging only add boot/runtime overhead.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    # Bind with a short retry loop. Under per-test-server isolation the runner
    # SIGKILLs the previous server and immediately re-invokes start.sh; the old
    # socket can still be in TIME_WAIT/closing when the new process binds. A
    # transient "Address already in use" must NOT crash the boot — that would
    # surface as a spurious "could not be restarted" in the concurrent sweep.
    # make_server sets SO_REUSEADDR; we additionally retry briefly so the new
    # server reliably comes up within the runner's restart-poll window.
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
