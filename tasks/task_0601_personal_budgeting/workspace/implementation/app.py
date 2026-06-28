"""Flask entry point for the Personal Budgeting & Account Aggregation API.

Wires every blueprint, registers the standard error envelope handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000). The in-memory
store starts EMPTY on every boot — no seeding.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.households import bp as households_bp
from routes.members import bp as members_bp
from routes.accounts import bp as accounts_bp
from routes.transactions import bp as transactions_bp
from routes.category_rules import bp as category_rules_bp
from routes.budget_periods import bp as budget_periods_bp
from routes.budget_categories import bp as budget_categories_bp
from routes.goals import bp as goals_bp
from routes.recurring_bills import bp as recurring_bills_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(households_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(category_rules_bp)
    app.register_blueprint(budget_periods_bp)
    app.register_blueprint(budget_categories_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(recurring_bills_bp)

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
