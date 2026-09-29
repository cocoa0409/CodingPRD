"""Theatrical Capitalization & Investor Reporting API.

Flask application factory and process entry point.  All state lives in memory
(see db.py) and is discarded when the process exits: the harness relaunches this
server before every test, and every run starts from an empty store.
"""

import os

from flask import Flask

import errors
import response
from routes import (budget_lines, clock, closing_notices, distributions,
                    engagements, investor_accounts, investors,
                    offering_documents, operating_budgets, productions,
                    royalty_allocations, royalty_participants, subscriptions,
                    subsidiary_rights, theatres, weekly_wraps)

BLUEPRINTS = (
    theatres.bp,
    productions.bp,
    engagements.bp,
    budget_lines.bp,
    operating_budgets.bp,
    offering_documents.bp,
    investors.bp,
    subscriptions.bp,
    investor_accounts.bp,
    royalty_participants.bp,
    weekly_wraps.bp,
    royalty_allocations.bp,
    subsidiary_rights.bp,
    distributions.bp,
    closing_notices.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(404)
    def not_found(_exc):
        return response.error(errors.ERR_INVALID_REQUEST,
                             "No such route.", 404)

    @app.errorhandler(405)
    def method_not_allowed(_exc):
        return response.error(errors.ERR_INVALID_REQUEST,
                              "Method not allowed for this route.", 405)

    @app.errorhandler(errors.ApiError)
    def api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(Exception)
    def unhandled(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return response.error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
