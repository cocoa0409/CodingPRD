"""Employer Tuition Benefit Administration API.

Storage is in-memory only and starts empty on every boot; every entity is
created by clients through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from domain import refresh_all_employees
from envelope import error_response
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    register_routes(app)

    @app.before_request
    def _refresh_clock_derived_state():
        # Derived employee state follows the logical clock, so it is refreshed
        # before the request is served; this never bumps a version.
        refresh_all_employees()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        status = error.code or 500
        if status == 404:
            return error_response("ERR_NOT_FOUND", "the requested resource does not exist", 404)
        if status == 405:
            return error_response(
                "ERR_NOT_FOUND", "the method is not allowed on this path", 405
            )
        if status == 400:
            return error_response("ERR_INVALID_REQUEST", "the request could not be parsed", 400)
        return error_response("ERR_INTERNAL", error.description or "request failed", status)

    @app.errorhandler(Exception)
    def _unexpected(error):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
