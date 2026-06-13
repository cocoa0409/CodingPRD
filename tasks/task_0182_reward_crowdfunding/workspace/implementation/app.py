"""Reward Crowdfunding API — entry point, error handlers, route registration.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.participants import bp as participants_bp
from routes.campaigns import bp as campaigns_bp
from routes.catalog import bp as catalog_bp
from routes.pledges import bp as pledges_bp
from routes.events import bp as events_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(participants_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(pledges_bp)
    app.register_blueprint(events_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route — treat as not found in our envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        return error_response("ERR_INVALID_REQUEST", str(e), e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % e, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
