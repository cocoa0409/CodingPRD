"""Campus Parking & Transportation Demand Management API — Flask entry point.

In-memory only. Boots empty on every invocation; no seeding.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error as error_response

from routes.patrons import bp as patrons_bp
from routes.lots import bp as lots_bp
from routes.allocations import bp as allocations_bp
from routes.waitlist import bp as waitlist_bp
from routes.permits import bp as permits_bp
from routes.citations import bp as citations_bp
from routes.closures import bp as closures_bp
from routes.shuttles import bp as shuttles_bp
from routes.incentives import bp as incentives_bp
from routes.funds import bp as funds_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(patrons_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(allocations_bp)
    app.register_blueprint(waitlist_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(citations_bp)
    app.register_blueprint(closures_bp)
    app.register_blueprint(shuttles_bp)
    app.register_blueprint(incentives_bp)
    app.register_blueprint(funds_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
