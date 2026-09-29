"""Broadband Grant Challenge API — Flask application factory and entry point.

Storage is in-memory only and starts completely empty on every boot; nothing is
ever seeded.  The harness relaunches this process before every test.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import DEFAULT_MESSAGES, ERROR_STATUS, ApiError
from response import error_response
from routes import register_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    register_all(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "No API route matches the requested path.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "The HTTP method is not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  DEFAULT_MESSAGES["ERR_INVALID_REQUEST"], 400)
        return error_response("ERR_INTERNAL", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "An unexpected server error occurred.",
                              ERROR_STATUS.get("ERR_INTERNAL", 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
