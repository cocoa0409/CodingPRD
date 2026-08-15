"""Mobile Car Wash & Fleet Washing Service API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from util import error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found"))

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found"))

    @app.errorhandler(400)
    def _bad_request(_err):
        return error_response(ApiError(ERR_VALIDATION, "Malformed request"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
