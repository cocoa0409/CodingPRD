"""Airline live animal / pet travel acceptance service.

Flask application factory and process entry point. Storage is in-memory only and
starts completely empty on every boot: nothing is seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (animals, catalog, clock, documents, flights, incidents, kennels,
                    reservations, segments)

MODULES = (catalog, flights, reservations, animals, segments, documents, kennels,
           incidents, clock)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in MODULES:
        module.init(app)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if error.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed for this resource", 405)
        if error.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)
        return error_response("ERR_INTERNAL", error.description or "Internal error",
                              error.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
