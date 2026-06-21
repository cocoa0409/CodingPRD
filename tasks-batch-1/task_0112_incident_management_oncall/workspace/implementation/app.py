"""Incident Management & On-Call API — entry point, error handlers, routing."""
import logging
import os
import socket

# Werkzeug's dev server calls socket.getfqdn(host) during server_bind purely to
# compose its "Running on http://..." startup log line. On this host (macOS) a
# reverse-DNS (PTR) lookup for the unspecified address 0.0.0.0 blocks ~5s before
# timing out. Under per-test-server isolation the server is rebooted before every
# test, so that 5s stall is paid hundreds of times and, during the concurrent
# 8-round stability sweep, can push a single boot past the runner's restart-poll
# window and surface as a spurious "could not be restarted". Short-circuit the
# lookup for the unspecified-address cases only — this changes nothing but the
# cosmetic banner hostname; the server still binds 0.0.0.0 and serves identical
# responses.
_orig_getfqdn = socket.getfqdn


def _fast_getfqdn(name="", _orig=_orig_getfqdn):
    if name in ("", "0.0.0.0", "::"):
        return "localhost"
    return _orig(name)


socket.getfqdn = _fast_getfqdn

from flask import Flask

import response
from errors import ApiError
from routes.services_routes import bp as services_bp
from routes.responders_routes import bp as responders_bp
from routes.schedules_routes import bp as schedules_bp
from routes.policies_routes import bp as policies_bp
from routes.windows_routes import bp as windows_bp
from routes.incidents_routes import bp as incidents_bp
from routes.war_rooms_routes import bp as war_rooms_bp
from routes.postmortems_routes import bp as postmortems_bp
from routes.action_items_routes import bp as action_items_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        services_bp,
        responders_bp,
        schedules_bp,
        policies_bp,
        windows_bp,
        incidents_bp,
        war_rooms_bp,
        postmortems_bp,
        action_items_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return response.error("ERR_INCIDENT_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error("ERR_INVALID_REQUEST", "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return response.error("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        return response.error("ERR_INVALID_REQUEST", f"Unexpected error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Silence Werkzeug's per-request access log. Under per-test-server isolation
    # the server is rebooted before every test and the readiness probe plus each
    # request would otherwise emit a log line to stderr; suppressing it removes
    # I/O syscall overhead during the concurrent 8-round stability sweep, which
    # widens the margin against the runner's restart-poll window. No behavior
    # change — responses are byte-identical.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=port, threaded=True)
