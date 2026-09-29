"""Cord Blood Banking — Unit Release API (Flask, in-memory).

The process holds all state in module-level dicts and starts completely empty on
every boot: nothing is seeded, preloaded or hardcoded anywhere.  The test
harness relaunches this process before every individual test.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "Method not allowed for this resource.", 405)

    @app.errorhandler(400)
    def _handle_400(exc):
        return error_response("ERR_VALIDATION_FAILED",
                              "Request body must be a JSON object.", 422)

    @app.errorhandler(415)
    def _handle_415(exc):
        return error_response("ERR_VALIDATION_FAILED",
                              "Request body must be JSON.", 422)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            return error_response("ERR_VALIDATION_FAILED", exc.description or "",
                                  422 if exc.code == 400 else exc.code)
        return error_response("ERR_VALIDATION_FAILED", str(exc), 422)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=True)
