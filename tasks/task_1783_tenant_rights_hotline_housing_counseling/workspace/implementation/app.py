"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask

from errors import ApiError
from response import error_body

import routes_reference
import routes_scripts
import routes_callers
import routes_sessions
import routes_cases
import routes_referrals
import routes_privacy
import routes_ops


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        routes_reference,
        routes_scripts,
        routes_callers,
        routes_sessions,
        routes_cases,
        routes_referrals,
        routes_privacy,
        routes_ops,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_body("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_body("ERR_INVALID_REQUEST", "method not allowed", 405)

    @app.errorhandler(400)
    def handle_bad_request(err):
        return error_body("ERR_INVALID_REQUEST", "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_body("ERR_INVALID_REQUEST", "internal error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
