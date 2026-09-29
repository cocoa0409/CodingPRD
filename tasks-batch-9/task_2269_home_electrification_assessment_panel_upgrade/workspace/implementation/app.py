"""Home Electrification Rebates API -- Flask entry point.

Storage is process-local and in-memory only; a fresh process starts with every
collection empty. No entity data is ever seeded.
"""
import os

from flask import Flask

import envelope
import errors
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return envelope.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def handle_not_found(_error):
        return envelope.error_response(
            errors.ERR_NOT_FOUND, "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return envelope.error_response(
            errors.ERR_METHOD_NOT_ALLOWED, "The method is not allowed for this path.", 405)

    @app.errorhandler(400)
    def handle_bad_request(_error):
        return envelope.error_response(
            errors.ERR_INVALID_REQUEST, "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return envelope.error_response(error.error_id, error.message, error.http_status)
        app.logger.exception("Unhandled error: %s", error)
        return envelope.error_response(
            errors.ERR_INTERNAL, "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
