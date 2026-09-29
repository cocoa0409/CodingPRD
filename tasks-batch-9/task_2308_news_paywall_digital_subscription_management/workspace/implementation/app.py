"""Flask application factory for the news paywall / subscription service.

Storage is process-local and in-memory only (see db.py): a fresh process starts
with every collection empty and the logical clock at 2026-08-01T00:00:00Z.
Nothing is seeded, read from disk or cached outside this process.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import config
from errors import ApiError
from response import error_response
from routes import (
    access_decisions,
    articles,
    billing_runs,
    cancellations,
    clock_control,
    group_accounts,
    holds,
    invoices,
    offer_plans,
    paywall_rules,
    readers,
    subscriptions,
)

BLUEPRINTS = (
    offer_plans.bp,
    paywall_rules.bp,
    articles.bp,
    readers.bp,
    access_decisions.bp,
    subscriptions.bp,
    holds.bp,
    invoices.bp,
    cancellations.bp,
    group_accounts.bp,
    billing_runs.bp,
    clock_control.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=config.API_PREFIX)

    @app.before_request
    def _begin_request():
        # PRD 2.5: one version bump per entity per request, and entities created
        # in this request stay at version 1.
        g.touched_ids = set()
        g.created_ids = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "That method is not allowed for this resource.",
                405,
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request body could not be parsed.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
