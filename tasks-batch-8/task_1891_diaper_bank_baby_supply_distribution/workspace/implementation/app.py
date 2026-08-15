"""Entry point: Flask app, error handlers, route registration (PRD §4)."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response
from routes import register_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response(ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1],
                                       "Resource not found."))

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response(ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1],
                                       "Resource not found."))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError(ERR_VALIDATION[0], 500,
                                       "Internal error: %s" % err))

    register_all(app)
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
