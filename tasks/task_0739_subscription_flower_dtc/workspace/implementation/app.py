"""Entry point for the Subscription-Flower DTC API."""
import os
from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST
from response import err
from routes.plans import bp as plans_bp
from routes.carrier_routes import bp as routes_bp
from routes.substitution_rules import bp as sub_rules_bp
from routes.clock import bp as clock_bp
from routes.customers import bp as customers_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.shipments import bp as shipments_bp
from routes.stem_lots import bp as lots_bp
from routes.charges import bp as charges_bp
from routes.win_back_offers import bp as offers_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (plans_bp, routes_bp, sub_rules_bp, clock_bp, customers_bp,
               subscriptions_bp, shipments_bp, lots_bp, charges_bp, offers_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_flask_404(e):
        # Path did not match any registered route.
        return err(ERR_INVALID_REQUEST, "unknown endpoint", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return err(ERR_INVALID_REQUEST, "method not allowed", 405)

    @app.errorhandler(400)
    def handle_bad_request(e):
        return err(ERR_INVALID_REQUEST, "invalid request", 400)

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        # Shouldn't happen — keep 500 handler minimal.
        return err("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Threaded off — in-memory state, and tests are sequential per per-test-server.
    app.run(host="0.0.0.0", port=port, threaded=False, use_reloader=False)
