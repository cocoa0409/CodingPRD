"""State Veterans Home Admission and Per Diem API.

Flask application factory and entrypoint. Storage is entirely in-memory and
nothing is seeded: every entity is created through the declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_applicants
import routes_claims
import routes_finance
import routes_homes
import routes_ops
import routes_residents
from common import ApiError, error_response

PREFIX = "/svh"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_homes,
        routes_applicants,
        routes_residents,
        routes_finance,
        routes_claims,
        routes_ops,
    ):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response(
            "ERR_INVALID_REQUEST", "The HTTP method is not allowed for this route.", 405
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request.", 422)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
