"""Legal Matter Budgeting & Alternative Fee Arrangements API — entry point.

Flask app wiring: blueprint registration, error handlers, 0.0.0.0:$PORT.
The store (db.py) starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_MISSING_HEADERS,
    ERR_NOT_FOUND,
)
from response import error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        firms,
        timekeepers,
        clients,
        matters,
        fee_arrangements,
        phase_budgets,
        time_entries,
        write_downs,
        amendments,
        accrual_reports,
        collar_true_ups,
        misc,
    )

    for module in (
        firms, timekeepers, clients, matters, fee_arrangements, phase_budgets,
        time_entries, write_downs, amendments, accrual_reports, collar_true_ups,
        misc,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error(ERR_NOT_FOUND, "Resource id does not exist within the firm scope", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        return error(ERR_MISSING_HEADERS, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error(ERR_INVALID_REQUEST, f"Unexpected error: {exc}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
