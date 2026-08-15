"""Freight Audit & Payment Services API — Flask entry point.

In-memory store only; every process boot starts with zero state.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    import routes
    routes.register_all(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404,
                                       "Referenced resource does not exist"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError(ERR_INVALID_REQUEST, 400,
                                       "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError(ERR_INVALID_REQUEST, 400,
                                       "Unexpected request failure: %s" % err))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
