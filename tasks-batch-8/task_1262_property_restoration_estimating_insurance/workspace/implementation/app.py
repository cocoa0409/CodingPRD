"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, error_response
import routes_a
import routes_b


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        # Unknown paths / wrong methods still answer in the envelope.
        if err.code == 404:
            mapped = ApiError("ERR_RESOURCE_NOT_FOUND", "Resource not found")
        elif err.code == 405:
            mapped = ApiError("ERR_RESOURCE_NOT_FOUND", "Method not allowed")
            mapped.http_status = 405
        elif err.code == 400:
            mapped = ApiError("ERR_INVALID_REQUEST", "Bad request")
        else:
            mapped = ApiError("ERR_INVALID_REQUEST", err.name)
            mapped.http_status = err.code or 500
        return error_response(mapped)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        mapped = ApiError("ERR_INVALID_REQUEST", str(err))
        mapped.http_status = 500
        return error_response(mapped)

    routes_a.register(app)
    routes_b.register(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
