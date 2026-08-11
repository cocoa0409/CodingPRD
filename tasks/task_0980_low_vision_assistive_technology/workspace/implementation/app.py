"""Flask entry point: error handlers, route registration, server boot."""

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clients import bp as clients_bp
from routes.referrals import bp as referrals_bp
from routes.evaluations import bp as evaluations_bp
from routes.catalog import bp as catalog_bp
from routes.device_orders import bp as device_orders_bp
from routes.loans import bp as loans_bp
from routes.training import bp as training_bp
from routes.funding import bp as funding_bp
from routes.claims import bp as claims_bp
from routes.repairs import bp as repairs_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.outcomes import bp as outcomes_bp
from routes.ops import bp as ops_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(clients_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(device_orders_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(training_bp)
    app.register_blueprint(funding_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(repairs_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(outcomes_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(_):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))

    @app.errorhandler(400)
    def handle_400(_):
        return error_response(ApiError("ERR_VALIDATION", 400, "Malformed request"))

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Never leak internals; report as validation-style 500
        return error_response(ApiError("ERR_INTERNAL", 500, f"Internal error: {type(err).__name__}"))

    return app


app = create_app()

if __name__ == "__main__":
    import time

    port = int(os.environ.get("PORT", "10000"))
    # per-test-server isolation SIGKILLs the previous server and boots a new
    # one on the same port; if the kernel has not fully released the listen
    # socket yet, bind() raises OSError. Retry briefly instead of dying,
    # which the runner would surface as "could not be restarted".
    for _attempt in range(20):
        try:
            app.run(host="0.0.0.0", port=port)
            break
        except OSError:
            time.sleep(0.5)
