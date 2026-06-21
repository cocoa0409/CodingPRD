"""Entry point: app factory, error handlers, blueprint registration.

In-memory only; the store starts empty on every boot (no seeding). The server
binds 0.0.0.0 on $PORT (default 10000) and runs in the foreground.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.commissaries import bp as commissaries_bp
from routes.trucks import bp as trucks_bp
from routes.permits import bp as permits_bp
from routes.spots import bp as spots_bp
from routes.events import bp as events_bp
from routes.bookings import bp as bookings_bp
from routes.menu_items import bp as menu_items_bp
from routes.prep_batches import bp as prep_batches_bp
from routes.staff_shifts import bp as staff_shifts_bp
from routes.utility_logs import bp as utility_logs_bp
from routes.orders import bp as orders_bp
from routes.order_lines import bp as order_lines_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(commissaries_bp)
    app.register_blueprint(trucks_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(spots_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(menu_items_bp)
    app.register_blueprint(prep_batches_bp)
    app.register_blueprint(staff_shifts_bp)
    app.register_blueprint(utility_logs_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(order_lines_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — keep envelope shape consistent.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
