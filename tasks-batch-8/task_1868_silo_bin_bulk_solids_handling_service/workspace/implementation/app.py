"""Flask application entry point for the Silo/Bin Bulk-Solids Service API."""
import os
from flask import Flask, jsonify

import errors as errmod
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.sites import bp as sites_bp
    from routes.technicians import bp as tech_bp
    from routes.vessels import bp as vessels_bp
    from routes.level_readings import bp as measurements_bp
    from routes.orders import bp as orders_bp
    from routes.tickets import bp as tickets_bp
    from routes.permits import bp as permits_bp
    from routes.clock import bp as clock_bp

    app.register_blueprint(sites_bp)
    app.register_blueprint(tech_bp)
    app.register_blueprint(vessels_bp)
    app.register_blueprint(measurements_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errmod.ApiError)
    def handle_api_error(e: errmod.ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(errmod.ERR_VALIDATION, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected exceptions as a 500 in the standard envelope.
        return error_response("ERR_INTERNAL", f"Internal server error: {e}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
