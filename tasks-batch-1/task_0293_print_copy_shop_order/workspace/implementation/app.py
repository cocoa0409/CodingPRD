"""Print & Copy Shop Order API — Flask entry point.

Registers all route blueprints and the global error handlers that render the
standard error envelope (PRD §2.2). The in-memory store (db.py) starts empty on
every boot — NO entity is seeded, preloaded, or hardcoded at startup.
"""

import os

from flask import Flask

from errors import ApiError
import response

from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.orders import bp as orders_bp
from routes.order_lines import bp as order_lines_bp
from routes.artworks import bp as artworks_bp
from routes.proofs import bp as proofs_bp
from routes.fulfillments import bp as fulfillments_bp
from routes.press_bookings import bp as press_bookings_bp
from routes.capacity import bp as capacity_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(order_lines_bp)
    app.register_blueprint(artworks_bp)
    app.register_blueprint(proofs_bp)
    app.register_blueprint(fulfillments_bp)
    app.register_blueprint(press_bookings_bp)
    app.register_blueprint(capacity_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error_response("ERR_NOT_FOUND",
                                       "Method not allowed for this path", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return response.error_response("ERR_VALIDATION", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error_response(exc.error_id, exc.message, exc.http_status)
        # Surface unexpected faults as a generic validation error rather than a
        # bare 500 HTML page (keeps the envelope contract intact).
        return response.error_response("ERR_VALIDATION", "Unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
