"""Entry point. Registers blueprints, error handlers, and boots Flask on 0.0.0.0:$PORT."""
import os

from flask import Flask, jsonify

from errors import ApiError, ERROR_HTTP
from response import error_response

# Route modules.
from routes.creators import bp as creators_bp
from routes.storefronts import bp as storefronts_bp
from routes.products import bp as products_bp
from routes.designs import bp as designs_bp
from routes.listings import bp as listings_bp
from routes.orders import bp as orders_bp
from routes.fulfillment import bp as fulfillment_bp
from routes.payouts import bp as payouts_bp
from routes.test_ops import bp as test_ops_bp


def create_app():
    app = Flask(__name__)

    # Register blueprints.
    for bp in (
        creators_bp,
        storefronts_bp,
        products_bp,
        designs_bp,
        listings_bp,
        orders_bp,
        fulfillment_bp,
        payouts_bp,
        test_ops_bp,
    ):
        app.register_blueprint(bp)

    # ---- Error handlers ----
    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "route not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    @app.errorhandler(Exception)
    def handle_generic(exc):
        # Fall back to a 500 in the standard envelope for unexpected server errors.
        # Include the exception message for easier debugging without leaking secrets.
        return error_response("ERR_INVALID_REQUEST", f"internal error: {exc}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Threading enables concurrent requests during test bursts.
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
