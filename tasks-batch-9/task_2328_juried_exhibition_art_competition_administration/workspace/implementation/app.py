"""Juried Exhibition Administration API.

Boots a fresh, empty in-memory store on every process start.  No data is ever
seeded, cached to disk or read back from a previous run.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import error_response
from errors import ApiError
import routes_artworks
import routes_entries
import routes_exhibitions
import routes_finance
import routes_jury


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_exhibitions.bp)
    app.register_blueprint(routes_entries.bp)
    app.register_blueprint(routes_artworks.bp)
    app.register_blueprint(routes_jury.bp)
    app.register_blueprint(routes_finance.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.")
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.")
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request.")
        return error_response("ERR_INTERNAL", exc.description or "Unexpected error.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", "Unexpected server error.")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
