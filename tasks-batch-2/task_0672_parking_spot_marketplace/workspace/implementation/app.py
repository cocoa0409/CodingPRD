"""Entry point: app factory, error handlers, blueprint registration.

The store starts empty on every boot — no seeding. The test harness restarts this
process before every pytest test (per-test-server isolation).
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_FORBIDDEN_ROLE
from response import error_response

from routes.hosts import bp as hosts_bp
from routes.drivers import bp as drivers_bp
from routes.spots import bp as spots_bp
from routes.pricing_events import bp as pricing_events_bp
from routes.bookings import bp as bookings_bp
from routes.access_passes import bp as access_passes_bp
from routes.transfer_offers import bp as transfer_offers_bp
from routes.violations import bp as violations_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(hosts_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(spots_bp)
    app.register_blueprint(pricing_events_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(access_passes_bp)
    app.register_blueprint(transfer_offers_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> not found.
        return error_response(ERR_NOT_FOUND[0], "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path -> forbidden role (operation not permitted).
        return error_response(ERR_FORBIDDEN_ROLE[0], "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected errors in the standard envelope rather than HTML.
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
