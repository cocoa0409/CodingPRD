"""Window Fenestration Manufacturing API — Flask entry point."""
import os

from flask import Flask

from common import ApiError, error_response
from routes_admin import bp_admin
from routes_orders import bp_orders
from routes_production import bp_production
from routes_shipping import bp_shipping
from routes_warranty import bp_warranty


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(bp_admin)
    app.register_blueprint(bp_orders)
    app.register_blueprint(bp_production)
    app.register_blueprint(bp_shipping)
    app.register_blueprint(bp_warranty)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", 500, f"Internal error: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
