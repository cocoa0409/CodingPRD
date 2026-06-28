"""Mobile & Bridal Beauty API — entry point, error handlers, route registration.

In-memory only: the store starts empty on every boot. NO seeding.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.artists import bp as artists_bp
from routes.events import bp as events_bp
from routes.trials import bp as trials_bp
from routes.contracts import bp as contracts_bp
from routes.assignments import bp as assignments_bp
from routes.invoices import bp as invoices_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(artists_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(trials_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {err}", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
