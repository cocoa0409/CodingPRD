"""Fastener Cold Heading & Thread Rolling API — entry point."""

import os
import sys
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND", "Unknown route."))
        if err.code == 405:
            return error_response(
                ApiError("ERR_VALIDATION", "Method not allowed for this route.")
            )
        if err.code == 400:
            return error_response(ApiError("ERR_VALIDATION", "Malformed request."))
        return error_response(
            ApiError("ERR_INTERNAL", err.description or "Request failed", err.code)
        )

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover - defensive
        traceback.print_exc(file=sys.stderr)
        return error_response(ApiError("ERR_INTERNAL", "Internal server error."))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
