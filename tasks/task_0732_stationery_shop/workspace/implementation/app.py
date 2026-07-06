"""Flask app entry point."""

import os
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import errors
import response as resp

# Import route modules to register blueprints
from routes.customers import bp as customers_bp
from routes.designers import bp as designers_bp
from routes.catalog import bp as catalog_bp
from routes.designs import bp as designs_bp
from routes.proofs import bp as proofs_bp
from routes.orders import bp as orders_bp
from routes.line_items import bp as line_items_bp
from routes.addressing import bp as addressing_bp
from routes.work_orders import bp as work_orders_bp
from routes.shipments import bp as shipments_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(designers_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(designs_bp)
    app.register_blueprint(proofs_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(line_items_bp)
    app.register_blueprint(addressing_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e: errors.ApiError):
        return resp.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return resp.error(errors.ERR_INVALID_REQUEST, "route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return resp.error(errors.ERR_INVALID_REQUEST, "method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return resp.error(errors.ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        return resp.error(errors.ERR_INVALID_REQUEST, e.description or "http error", e.code or 500)

    @app.errorhandler(Exception)
    def handle_generic(e):
        # Unexpected — surface as 500 with generic error id
        return resp.error(errors.ERR_INVALID_REQUEST, str(e), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
