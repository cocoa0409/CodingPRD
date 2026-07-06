"""Plant Shop Boutique API — Flask entrypoint.

Boots with empty in-memory state (no seeding). Binds 0.0.0.0:$PORT (default 10000).
"""
import os
import sys
from flask import Flask, request

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register blueprints.
    from routes.clock import bp as clock_bp
    from routes.customers import bp as customers_bp
    from routes.plants import bp as plants_bp
    from routes.drivers import bp as drivers_bp
    from routes.orders import bp as orders_bp
    from routes.deliveries import bp as deliveries_bp
    from routes.subscriptions import bp as subs_bp
    from routes.workshops import bp as workshops_bp
    from routes.warranty import bp as warranty_bp
    from routes.special_orders import bp as special_bp

    for bp in (clock_bp, customers_bp, plants_bp, drivers_bp, orders_bp,
               deliveries_bp, subs_bp, workshops_bp, warranty_bp, special_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e: ApiError):
        return error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return error(ERR_NOT_FOUND, "route not found", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return error(ERR_INVALID_REQUEST, "method not allowed", 400)

    @app.errorhandler(400)
    def handle_400(_e):
        return error(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        # Never leak internal errors — return a 500-flavored envelope.
        return error("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Use production-style server flags (no reloader, no debug) so the process
    # is deterministic under per-test-server isolation.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
