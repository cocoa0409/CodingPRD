"""Insurance Premium Finance API — Flask application entry point.

All state lives in process memory.  Nothing is seeded: every entity is
created through the API surface.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_admin
import routes_agreements
import routes_endorsements
import routes_servicing


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_agreements.bp)
    app.register_blueprint(routes_servicing.bp)
    app.register_blueprint(routes_endorsements.bp)

    @app.before_request
    def _reset_touch_set():
        g._touched = set()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_INVALID_REQUEST",
                                          "resource not found", 404))
        if err.code == 405:
            return error_response(ApiError("ERR_INVALID_REQUEST",
                                          "method not allowed", 405))
        if err.code and 400 <= err.code < 500:
            return error_response(ApiError("ERR_INVALID_REQUEST",
                                          err.description or "bad request",
                                          err.code))
        return error_response(ApiError("ERR_INVALID_REQUEST",
                                       "internal error", 500))

    @app.errorhandler(Exception)
    def _unhandled(err):  # pragma: no cover - defensive
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err), 500))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
