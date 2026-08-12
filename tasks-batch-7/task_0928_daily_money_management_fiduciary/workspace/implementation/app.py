"""Daily Money Management & Bill-Pay Fiduciary API.

Entry point: route registration and the single error handler that renders the
PRD section 2.2 error envelope.  Storage is in-memory only; nothing is seeded
at startup - the store is empty on every boot.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402

from core.envelope import error_response  # noqa: E402
from core.errors import ApiError  # noqa: E402
from routes import accounts, authorizations, benefits, bonds, budgets  # noqa: E402
from routes import clients, coordination, disputes, family, fraud  # noqa: E402
from routes import ops, payees, payments, reconciliation  # noqa: E402

BLUEPRINTS = (
    clients.bp,
    authorizations.bp,
    accounts.bp,
    payees.bp,
    budgets.bp,
    payments.bp,
    disputes.bp,
    reconciliation.bp,
    fraud.bp,
    benefits.bp,
    bonds.bp,
    family.bp,
    coordination.bp,
    ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "No such route.", 404)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
