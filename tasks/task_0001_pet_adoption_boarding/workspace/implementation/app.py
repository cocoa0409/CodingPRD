"""Pet Adoption & Boarding Platform API — Flask entry point."""

import os
import traceback

from flask import Flask, request

from errors import APIError, HTTP_STATUS, ERR_INVALID_REQUEST, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
from response import error_response
from routes.shelters import bp as shelters_bp
from routes.animals import bp as animals_bp
from routes.adopters import bp as adopters_bp
from routes.applications import bp as applications_bp
from routes.boarding import bp as boarding_bp
from routes.settlements import bp as settlements_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(shelters_bp)
    app.register_blueprint(animals_bp)
    app.register_blueprint(adopters_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(boarding_bp)
    app.register_blueprint(settlements_bp)

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Flask's own 404 for unregistered routes — return a generic not-found response
        return error_response("ERR_INVALID_REQUEST", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_exception(err):
        if isinstance(err, APIError):
            return handle_api_error(err)
        traceback.print_exc()
        return error_response(ERR_INVALID_REQUEST, f"Internal error: {err}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
