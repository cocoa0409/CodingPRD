"""Tax Amnesty & Voluntary Disclosure Administration API.

State is held in process memory only and starts completely empty on every boot.
"""

import os

from flask import Flask

import response
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        # malformed JSON reaches us as a werkzeug BadRequest
        return response.error_response(ApiError("ERR_INVALID_REQUEST"))

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return response.error_response(
            ApiError("ERR_ROUTE_NOT_FOUND", "No such route", 404))

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return response.error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed on this route", 405))

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error_response(exc)
        app.logger.exception("unhandled error")
        return response.error_response(
            ApiError("ERR_INTERNAL", "Unexpected server error", 500))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        debug=False,
        threaded=True,
        use_reloader=False,
    )
