"""Flask entry point for the Cryotherapy & Recovery Lounge API.

Wires every blueprint, registers the standard error envelope handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000). The in-memory
store starts EMPTY on every boot — no seeding.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.admin_ops import bp as admin_ops_bp
from routes.locations import bp as locations_bp
from routes.service_types import bp as service_types_bp
from routes.rooms import bp as rooms_bp
from routes.technicians import bp as technicians_bp
from routes.membership_plans import bp as membership_plans_bp
from routes.members import bp as members_bp
from routes.waivers import bp as waivers_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.invoices import bp as invoices_bp
from routes.credit_packs import bp as credit_packs_bp
from routes.bookings import bp as bookings_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(admin_ops_bp)
    app.register_blueprint(locations_bp)
    app.register_blueprint(service_types_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(technicians_bp)
    app.register_blueprint(membership_plans_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(waivers_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(credit_packs_bp)
    app.register_blueprint(bookings_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
