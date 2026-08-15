"""Wire Transfer Operations & Sanctions Screening API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error_envelope
from routes import register_routes


def create_app():
    app = Flask(__name__)
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_envelope(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_envelope("ERR_NOT_FOUND", 404, "The requested resource does not exist.")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_envelope("ERR_NOT_FOUND", 404, "The requested resource does not exist.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_envelope("ERR_INVALID_REQUEST", 400, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
