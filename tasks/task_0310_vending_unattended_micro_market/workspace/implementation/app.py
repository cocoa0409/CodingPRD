"""Entry point: Flask app, error handlers, blueprint registration.

In-memory only; store starts empty on every boot (no seeding).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.host_sites import bp as host_sites_bp
from routes.products import bp as products_bp
from routes.machines import bp as machines_bp
from routes.slots import bp as slots_bp
from routes.lots import bp as lots_bp
from routes.drivers import bp as drivers_bp
from routes.routes_ import bp as routes_bp
from routes.stops import bp as stops_bp
from routes.visits import bp as visits_bp
from routes.sales import bp as sales_bp
from routes.statements import bp as statements_bp
from routes.tickets import bp as tickets_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (host_sites_bp, products_bp, machines_bp, slots_bp, lots_bp,
               drivers_bp, routes_bp, stops_bp, visits_bp, sales_bp,
               statements_bp, tickets_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route path — generic invalid request shape.
        return error_response("ERR_INVALID_REQUEST", "Resource path not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

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
