"""Laundromat & Self-Service Laundry API — Flask entry point.

In-memory only. Storage is process-local dicts (see db.py); a fresh process
starts with an empty store. No entity is seeded at startup. The test harness
relaunches this server (per-test) so each test runs against an empty database.
"""
import os
import socket as _socket

# --- Fast boot: neutralize the macOS reverse-DNS (PTR) stall -----------------
# Werkzeug's dev server calls socket.getfqdn(host) during server_bind purely to
# compose its "Running on http://..." startup log line. On macOS getfqdn for the
# unspecified address (0.0.0.0) blocks ~5s on a reverse-DNS lookup that times
# out. Under per-test-server isolation the server reboots before every test, so
# that 5s stall is paid on every restart and pushes setup past the 10s per-test
# timeout. We short-circuit getfqdn for unspecified addresses only; the server
# still binds 0.0.0.0 and serves identical responses. (Mirrors the runner's
# injected sitecustomize; applied here so boot is fast regardless of PYTHONPATH.)
_real_getfqdn = _socket.getfqdn
_UNSPECIFIED_ADDRS = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}


def _fast_getfqdn(name=""):
    if name in _UNSPECIFIED_ADDRS:
        return "localhost"
    return _real_getfqdn(name)


_socket.getfqdn = _fast_getfqdn

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.pricing_plans import bp as pricing_plans_bp
from routes.machines import bp as machines_bp
from routes.members import bp as members_bp
from routes.transactions import bp as transactions_bp
from routes.shifts import bp as shifts_bp
from routes.wdf_orders import bp as wdf_orders_bp
from routes.refund_claims import bp as refund_claims_bp
from routes.lost_found import bp as lost_found_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(pricing_plans_bp)
    app.register_blueprint(machines_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(wdf_orders_bp)
    app.register_blueprint(refund_claims_bp)
    app.register_blueprint(lost_found_bp)
    app.register_blueprint(clock_bp)

    @app.after_request
    def _no_keep_alive(resp):
        # Under per-test-server isolation the server is killed and relaunched
        # before every test, but the test client reuses a session-scoped
        # keep-alive connection. Forcing the connection closed after each
        # response prevents the client from reusing a socket bound to a
        # now-dead server process (which would hang the next request).
        resp.headers["Connection"] = "close"
        return resp

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / path resource not found -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Malformed JSON and similar client errors surface as 422 invalid request.
        if e.code and 400 <= e.code < 500:
            return error_response("ERR_INVALID_REQUEST", e.description or "Invalid request", 422)
        return error_response("ERR_INTERNAL", e.description or "Internal error", e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
