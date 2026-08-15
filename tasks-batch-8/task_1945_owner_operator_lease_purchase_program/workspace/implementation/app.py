"""Flask entry point: error handlers + route registration. No seeding at startup."""

import os

from flask import Flask

import errors as errmod
from response import error as error_response

from routes.operators import bp as operators_bp
from routes.trucks import bp as trucks_bp
from routes.leases import bp as leases_bp
from routes.settlements import bp as settlements_bp
from routes.escrow import bp as escrow_bp
from routes.lanes import bp as lanes_bp
from routes.maintenance import bp as maintenance_bp
from routes.compliance import bp as compliance_bp
from routes.buyout import bp as buyout_bp
from routes.clock_routes import bp as clock_bp

API_PREFIX = "/lease-program"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(errmod.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(
            errmod.ERR_INVALID_REQUEST, "Resource not found", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response(
            errmod.ERR_INVALID_REQUEST, "Method not allowed", 405
        )

    @app.errorhandler(500)
    def handle_internal(e):
        return error_response(
            errmod.ERR_INVALID_REQUEST, "Internal server error", 500
        )

    app.register_blueprint(operators_bp, url_prefix=API_PREFIX)
    app.register_blueprint(trucks_bp, url_prefix=API_PREFIX)
    app.register_blueprint(leases_bp, url_prefix=API_PREFIX)
    app.register_blueprint(settlements_bp, url_prefix=API_PREFIX)
    app.register_blueprint(escrow_bp, url_prefix=API_PREFIX)
    app.register_blueprint(lanes_bp, url_prefix=API_PREFIX)
    app.register_blueprint(maintenance_bp, url_prefix=API_PREFIX)
    app.register_blueprint(compliance_bp, url_prefix=API_PREFIX)
    app.register_blueprint(buyout_bp, url_prefix=API_PREFIX)
    app.register_blueprint(clock_bp, url_prefix=API_PREFIX)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
