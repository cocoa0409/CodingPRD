"""Currency Transaction Reporting & Exemption Management API.

Entry point: error handlers, route registration, and the foreground server.
Reads PORT (default 10000), binds 0.0.0.0. The store starts empty on every
boot; all time reads the logical clock (default 2026-08-01T00:00:00Z).
"""
import os

import logging

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from db import store
from errors import ERR_INVALID_REQUEST, ApiError
from response import err

app = Flask(__name__)


@app.before_request
def _open_request():
    # Serialize the whole request so each mutation + its cascade is atomic.
    store.lock.acquire()
    g.fx = []


@app.teardown_request
def _close_request(_exc):
    try:
        store.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(exc):
    return err(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    status = exc.code if isinstance(exc.code, int) else 500
    if status == 404:
        message = "Resource or route not found"
    elif status == 405:
        message = "Method not allowed"
    else:
        message = exc.name
    return err(ERR_INVALID_REQUEST, message, status)


@app.errorhandler(Exception)
def _unexpected(exc):
    logging.exception("Unhandled error")
    return err("ERR_INTERNAL_SERVER_ERROR", "Internal server error: %s" % exc, 500)


# --- Route registration -----------------------------------------------------
from routes.aggregations import bp as aggregations_bp  # noqa: E402
from routes.alerts import bp as alerts_bp  # noqa: E402
from routes.audit import bp as audit_bp  # noqa: E402
from routes.branches import bp as branches_bp  # noqa: E402
from routes.cash import bp as cash_bp  # noqa: E402
from routes.clock import bp as clock_bp  # noqa: E402
from routes.ctrs import bp as ctrs_bp  # noqa: E402
from routes.customers import bp as customers_bp  # noqa: E402
from routes.exams import bp as exams_bp  # noqa: E402
from routes.exemptions import bp as exemptions_bp  # noqa: E402
from routes.sales import bp as sales_bp  # noqa: E402

for _bp in (
    clock_bp,
    branches_bp,
    customers_bp,
    cash_bp,
    sales_bp,
    aggregations_bp,
    ctrs_bp,
    exemptions_bp,
    alerts_bp,
    exams_bp,
    audit_bp,
):
    app.register_blueprint(_bp)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
        debug=False,
    )
