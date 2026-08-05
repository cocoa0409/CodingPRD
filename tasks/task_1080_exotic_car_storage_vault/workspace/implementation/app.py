"""Exotic & Seasonal Car Storage / Vehicle Vault API — entry point."""
import os

from flask import Flask, jsonify

from core import ApiError, error_response, _meta
from routes.facilities import bp as facilities_bp
from routes.members import bp as members_bp
from routes.vehicles import bp as vehicles_bp
from routes.agreements import bp as agreements_bp
from routes.service_orders import bp as service_orders_bp
from routes.delivery import bp as delivery_bp
from routes.waitlist import bp as waitlist_bp
from routes.inspections import bp as inspections_bp
from routes.invoices import bp as invoices_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (facilities_bp, members_bp, vehicles_bp, agreements_bp,
               service_orders_bp, delivery_bp, waitlist_bp, inspections_bp,
               invoices_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        if isinstance(err, ApiError):
            return error_response(err)
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
