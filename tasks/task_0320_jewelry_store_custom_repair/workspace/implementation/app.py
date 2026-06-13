"""Jewelry Store & Custom/Repair API — entry point, error handlers, routing.

In-memory only. Fresh process => empty store. No seeding at startup.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error as error_response

from routes.standing import bp as standing_bp
from routes.appraisals import bp as appraisals_bp
from routes.custom_orders import bp as custom_orders_bp
from routes.repair_tickets import bp as repair_tickets_bp
from routes.layaway_plans import bp as layaway_plans_bp
from routes.trade_ins import bp as trade_ins_bp
from routes.special_orders import bp as special_orders_bp
from routes.payments import bp as payments_bp
from routes.warranty_claims import bp as warranty_claims_bp
from routes.credit_ledger import bp as credit_ledger_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(standing_bp)
    app.register_blueprint(appraisals_bp)
    app.register_blueprint(custom_orders_bp)
    app.register_blueprint(repair_tickets_bp)
    app.register_blueprint(layaway_plans_bp)
    app.register_blueprint(trade_ins_bp)
    app.register_blueprint(special_orders_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(warranty_claims_bp)
    app.register_blueprint(credit_ledger_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route / path-referenced resource not found.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % err, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
