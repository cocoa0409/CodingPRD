"""Ship Chandlery & Vessel Provisioning API — Flask entry point.

Mounts all route blueprints, registers the ApiError handler, and serves on
0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask

from errors import ApiError, err_invalid_request
from response import error_response
from routes.core import bp as core_bp
from routes.catalog import bp as catalog_bp
from routes.requisition import bp as requisition_bp
from routes.quotation import bp as quotation_bp
from routes.order_delivery import bp as order_delivery_bp
from routes.invoice import bp as invoice_bp
from routes.complaint import bp as complaint_bp


def create_app():
    app = Flask(__name__)

    for bp in (core_bp, catalog_bp, requisition_bp, quotation_bp,
               order_delivery_bp, invoice_bp, complaint_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(err_invalid_request("resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(err_invalid_request("method not allowed"))

    @app.errorhandler(500)
    def handle_internal_error(err):
        return error_response(err_invalid_request("internal server error"))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
