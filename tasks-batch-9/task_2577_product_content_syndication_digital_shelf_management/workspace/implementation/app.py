"""Product Content Syndication & Digital Shelf Management API.

Entry point: registers the blueprints under /digital-shelf and installs the
error handlers that render the PRD 2.2 error envelope.  The in-memory store
starts EMPTY on every boot -- nothing is seeded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import alerts, config, deployments, governance, listings, media, products, syndication

PREFIX = "/digital-shelf"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (config, products, media, listings, governance, syndication,
                   deployments, alerts):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return envelope.error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return envelope.error_response("ERR_INVALID_REQUEST", "Malformed request", 400)
        return envelope.error_response("ERR_INTERNAL", exc.description or "Error",
                                       exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return envelope.error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
