"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Unregistered paths / wrong methods still answer in the envelope.
        status = err.code if err.code in (400, 401, 403, 404, 405, 409, 412, 422) else 404
        return error_response(ApiError(status, ERR_INVALID_REQUEST,
                                       err.description or "Request failed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError(500, ERR_INVALID_REQUEST, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
