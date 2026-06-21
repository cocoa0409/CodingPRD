"""Renovation Contractor Bidding API — entry point.

In-memory only. No seeding/preloading: every collection starts empty on boot.
"""
import os
import socket

# Werkzeug's BaseWSGIServer.server_bind() resolves the bound host's FQDN via a
# reverse-DNS lookup. When binding to 0.0.0.0 (required by the build contract)
# under the runner's DNS-isolation, that lookup blocks ~5s until it times out,
# which — multiplied across per-test-server reboots under the 8x concurrent
# stability sweep — pushes a single server boot past the runner's 15s restart
# window and surfaces as a flaky "server could not be restarted" setup error.
# The FQDN is only used to populate an informational server_name attribute, so
# short-circuiting the lookup is behaviour-preserving and makes 0.0.0.0 binds
# return in ~2ms.
socket.getfqdn = lambda *a, **k: "localhost"

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.homeowners import bp as homeowners_bp
from routes.contractors import bp as contractors_bp
from routes.projects import bp as projects_bp
from routes.scope_items import bp as scope_items_bp
from routes.bids import bp as bids_bp
from routes.escrows import bp as escrows_bp
from routes.draws import bp as draws_bp
from routes.lien_waivers import bp as lien_waivers_bp
from routes.change_orders import bp as change_orders_bp
from routes.disputes import bp as disputes_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(homeowners_bp)
    app.register_blueprint(contractors_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(scope_items_bp)
    app.register_blueprint(bids_bp)
    app.register_blueprint(escrows_bp)
    app.register_blueprint(draws_bp)
    app.register_blueprint(lien_waivers_bp)
    app.register_blueprint(change_orders_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http(err):
        # Generic HTTP exceptions (e.g., malformed requests) -> ERR_INVALID_REQUEST
        code = err.code or 400
        if code == 404:
            return response.error("ERR_NOT_FOUND", "Resource not found.", 404)
        return response.error("ERR_INVALID_REQUEST", err.description or "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return response.error("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
