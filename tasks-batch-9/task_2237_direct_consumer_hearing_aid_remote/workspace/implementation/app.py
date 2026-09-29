"""Direct-to-consumer hearing aid remote care API (Flask, in-memory)."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_finance
import routes_firmware
import routes_order
import routes_policy
import routes_provider
import routes_repair
import routes_test
import routes_trial
from flask import jsonify

from errors import ApiError
from resp import error_body


def error_response(error_id, message, status):
    return jsonify(error_body(error_id, message)), status

PREFIX = "/hearing-care"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for module in (routes_policy, routes_provider, routes_order, routes_trial,
                   routes_repair, routes_finance, routes_firmware, routes_test):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error_response("ERR_VALIDATION", "Malformed request body", 422)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_response("ERR_ROLE_NOT_PERMITTED", "Method not allowed for this path", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_RESOURCE_NOT_FOUND",
                                  "The requested resource does not exist", 404)
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "Malformed request", 422)
        return error_response("ERR_VALIDATION", exc.description, exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
