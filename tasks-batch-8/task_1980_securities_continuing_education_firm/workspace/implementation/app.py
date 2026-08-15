"""Securities Continuing Education & Firm Element API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error as error_response
from routes import (representatives, contents, sessions, enrollments,
                    assignments, plans, attestations, products, licenses,
                    blackouts, ops)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    for module in (representatives, contents, sessions, enrollments,
                   assignments, plans, attestations, products, licenses,
                   blackouts, ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404,
                                       "Resource not found"))

    @app.errorhandler(400)
    def handle_bad_request(err):
        return error_response(ApiError(ERR_INVALID_REQUEST, 400,
                                       "Malformed request"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", 500,
                                       "Internal server error: %s" % err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
