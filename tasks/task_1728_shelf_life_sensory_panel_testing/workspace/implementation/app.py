"""Entry point: Flask app wiring, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(
            ApiError("ERR_INVALID_REQUEST", 500, f"Internal error: {err}")
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
