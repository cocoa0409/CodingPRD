"""Flask entry point for the School Fundraising & Booster Programs API.

Wires every blueprint, registers the standard error envelope handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000). The in-memory
store starts EMPTY on every boot — no seeding.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.campaigns import bp as campaigns_bp
from routes.prize_tiers import bp as prize_tiers_bp
from routes.sellers import bp as sellers_bp
from routes.products import bp as products_bp
from routes.orders import bp as orders_bp
from routes.pledges import bp as pledges_bp
from routes.volunteers import bp as volunteers_bp
from routes.shifts import bp as shifts_bp
from routes.disbursements import bp as disbursements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(prize_tiers_bp)
    app.register_blueprint(sellers_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(pledges_bp)
    app.register_blueprint(volunteers_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(disbursements_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        # Unknown method on a known path — treat as not found per benchmark norm.
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 422)

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
