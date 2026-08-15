"""University Procurement & P-Card Program API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_body

from routes.clock import bp as clock_bp
from routes.departments import bp as departments_bp
from routes.vendors import bp as vendors_bp
from routes.grants import bp as grants_bp
from routes.contracts import bp as contracts_bp
from routes.requisitions import bp as requisitions_bp
from routes.solicitations import bp as solicitations_bp
from routes.purchase_orders import bp as purchase_orders_bp
from routes.invoices import bp as invoices_bp
from routes.pcards import bp as pcards_bp
from routes.pcard_transactions import bp as pcard_transactions_bp
from routes.surplus import bp as surplus_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        clock_bp,
        departments_bp,
        vendors_bp,
        grants_bp,
        contracts_bp,
        requisitions_bp,
        solicitations_bp,
        purchase_orders_bp,
        invoices_bp,
        pcards_bp,
        pcard_transactions_bp,
        surplus_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_body(ERR_INVALID_REQUEST, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_body(ERR_INVALID_REQUEST, "method not allowed", 400)

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return error_body(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", f"internal error: {exc}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
