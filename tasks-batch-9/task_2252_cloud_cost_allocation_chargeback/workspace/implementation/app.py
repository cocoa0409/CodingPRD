"""Cloud Cost Allocation & Chargeback API (Flask, in-memory)."""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db as store
from errors import ApiError
from response import error as error_response
from routes import (
    allocation_lines,
    allocation_runs,
    anomalies,
    budgets,
    business_units,
    clock,
    cloud_resources,
    commitments,
    cost_records,
    disputes,
    invoices,
    provisioning_requests,
    remediation,
    shared_cost_pools,
    tagging_policies,
    unit_economics,
)

BLUEPRINTS = (
    clock.bp,
    business_units.bp,
    tagging_policies.bp,
    provisioning_requests.bp,
    cloud_resources.bp,
    cost_records.bp,
    allocation_runs.bp,
    shared_cost_pools.bp,
    allocation_lines.bp,
    invoices.bp,
    disputes.bp,
    commitments.bp,
    remediation.bp,
    anomalies.bp,
    budgets.bp,
    unit_economics.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire_lock():
        store.db.lock.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release_lock(_exception=None):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                store.db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code in (404, 405):
            return error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code and 400 <= exc.code < 500:
            return error_response(
                "ERR_INVALID_REQUEST", exc.description or "Invalid request.", exc.code
            )
        return error_response(
            "ERR_INTERNAL", exc.description or "Internal server error.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
