"""Building Code Adoption & Amendment API — Flask entrypoint.

State lives only in the process (see db.py); every boot starts empty and
nothing is ever seeded, cached on disk or read back from a file.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes
from errors import ERROR_STATUS, ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    routes.register(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.", 405)
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request could not be understood.", 400)
        return response.error_response(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - safety net
        return response.error_response(
            "ERR_INTERNAL", "An unexpected error occurred: %s" % exc,
            ERROR_STATUS.get("ERR_INTERNAL", 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
