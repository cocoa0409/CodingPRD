"""Entry point: app factory, error handlers, blueprint registration."""
import os
from flask import Flask

from errors import ApiError
from response import error_response

from routes.customers import bp as customers_bp
from routes.products import bp as products_bp
from routes.inventory import bp as inventory_bp
from routes.orders import bp as orders_bp
from routes.tradeins import bp as tradeins_bp
from routes.preorders import bp as preorders_bp
from routes.consignments import bp as consignments_bp
from routes.disputes import bp as disputes_bp
from routes.specialorders import bp as specialorders_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        customers_bp,
        products_bp,
        inventory_bp,
        orders_bp,
        tradeins_bp,
        preorders_bp,
        consignments_bp,
        disputes_bp,
        specialorders_bp,
        admin_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 400)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
