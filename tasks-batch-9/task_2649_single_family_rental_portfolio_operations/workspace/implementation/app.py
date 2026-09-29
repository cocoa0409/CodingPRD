"""Single-Family Rental Portfolio Operations API.

Flask application factory and error handling.  All state lives in memory and is
empty on every boot; nothing is seeded.
"""
import os

from flask import Flask, jsonify

import routes_compliance
import routes_core
import routes_home
import routes_leasing
import routes_project
import routes_prospect
import routes_underwriting
import routes_vendor
import routes_workorder
import store
from envelope import error_response
from errors import ApiError, CATALOG

BLUEPRINTS = [
    routes_core.bp,
    routes_home.bp,
    routes_underwriting.bp,
    routes_vendor.bp,
    routes_project.bp,
    routes_workorder.bp,
    routes_prospect.bp,
    routes_leasing.bp,
    routes_compliance.bp,
]


def _plain_error(error_id, status):
    entry = CATALOG.get(error_id, {})
    body = {
        "meta": {
            "api_request_id": store.request_id(),
            "api_request_timestamp": store.iso_now(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": entry.get("message", "The request could not be processed."),
        },
    }
    return jsonify(body), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(400)
    def handle_bad_request(err):
        return _plain_error("ERR_INVALID_REQUEST", 400)

    @app.errorhandler(404)
    def handle_not_found(err):
        return _plain_error("ERR_INVALID_REQUEST", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return _plain_error("ERR_INVALID_REQUEST", 405)

    @app.errorhandler(500)
    def handle_server_error(err):  # pragma: no cover
        return _plain_error("ERR_INVALID_REQUEST", 500)

    @app.errorhandler(Exception)
    def handle_uncaught(err):  # pragma: no cover
        if isinstance(err, ApiError):
            return error_response(err)
        code = getattr(err, "code", None)
        if isinstance(code, int):
            return _plain_error("ERR_INVALID_REQUEST", code)
        return _plain_error("ERR_INVALID_REQUEST", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
