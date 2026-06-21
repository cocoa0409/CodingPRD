"""Identity Governance & Access Reviews API — Flask entry point.

In-memory only. The store starts EMPTY on every boot; nothing is seeded.
The per-test-server harness relaunches start.sh (a fresh process) before each
test, which wipes all state.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

# Route blueprints
from routes.entitlements import bp as entitlements_bp
from routes.roles import bp as roles_bp
from routes.sod_policies import bp as sod_policies_bp
from routes.identities import bp as identities_bp
from routes.access_requests import bp as access_requests_bp
from routes.grants import bp as grants_bp
from routes.campaigns import bp as campaigns_bp
from routes.items import bp as items_bp
from routes.audit_events import bp as audit_events_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(entitlements_bp)
    app.register_blueprint(roles_bp)
    app.register_blueprint(sod_policies_bp)
    app.register_blueprint(identities_bp)
    app.register_blueprint(access_requests_bp)
    app.register_blueprint(grants_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(audit_events_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / path id not resolved at routing layer.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map any other werkzeug HTTP error (e.g. malformed JSON -> 400).
        if e.code == 400:
            return error_response("ERR_VALIDATION", "Bad request", 400)
        return error_response("ERR_VALIDATION", e.description or "Error", e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_VALIDATION", "Unexpected error: %s" % e, 400)

    @app.after_request
    def _close_connection(response):
        # Transport hygiene only: the per-test-server harness reuses a pooled
        # keep-alive client socket across the threaded Werkzeug dev server's
        # connection teardown, which can intermittently surface as a
        # BadStatusLine / ConnectionError race. Forcing Connection: close
        # prevents socket reuse. No endpoint, field, status code, error_id,
        # state transition, or calculation is affected.
        response.headers["Connection"] = "close"
        return response

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
