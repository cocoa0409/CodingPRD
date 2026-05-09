"""Public Rental Housing API — Flask application entry point."""
import os
from flask import Flask

from errors import APIError
from response import error_response

from routes.programs import bp as programs_bp
from routes.sync_events import bp as sync_events_bp
from routes.applications import bp as applications_bp
from routes.housing_units import bp as housing_units_bp
from routes.allocations import bp as allocations_bp
from routes.contracts import bp as contracts_bp
from routes.rent_reductions import bp as rent_reductions_bp


def create_app() -> Flask:
    app = Flask(__name__)

    # All endpoints are mounted under the API prefix.
    app.register_blueprint(programs_bp)
    app.register_blueprint(sync_events_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(housing_units_bp)
    app.register_blueprint(allocations_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(rent_reductions_bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(500)
    def handle_500(e):
        return error_response("ERR_INVALID_REQUEST",
                              f"Internal error: {e}", 500)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
