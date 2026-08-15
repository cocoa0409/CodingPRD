"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_body
from routes import bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_body(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_body(ERR_INVALID_REQUEST, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_body(ERR_INVALID_REQUEST, "method not allowed", 405)

    @app.errorhandler(500)
    def handle_internal_error(e):
        return error_body(ERR_INVALID_REQUEST, "internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
