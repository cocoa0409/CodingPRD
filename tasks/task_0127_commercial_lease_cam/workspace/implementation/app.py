"""Commercial Lease & CAM Reconciliation API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
(via start.sh) before every test, so there is no carry-over state. Nothing is
ever seeded at startup — every entity is constructed via the declared endpoints.
"""
from __future__ import annotations

import os
import sys
import time
import socket

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.properties import bp as properties_bp
from routes.tenants import bp as tenants_bp
from routes.expense_pools import bp as expense_pools_bp
from routes.leases import bp as leases_bp
from routes.sales_reports import bp as sales_reports_bp
from routes.ti_draws import bp as ti_draws_bp
from routes.reconciliations import bp as reconciliations_bp
from routes.estoppels import bp as estoppels_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(properties_bp)
    app.register_blueprint(tenants_bp)
    app.register_blueprint(expense_pools_bp)
    app.register_blueprint(leases_bp)
    app.register_blueprint(sales_reports_bp)
    app.register_blueprint(ti_draws_bp)
    app.register_blueprint(reconciliations_bp)
    app.register_blueprint(estoppels_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, str(e), 400)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), e.code or 500)
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


def _bind_with_retry(host: str, port: int, attempts: int = 40, delay: float = 0.25):
    """Survive same-port bind races under per-test-server isolation.

    The previous server may not have fully released the port when the runner
    relaunches start.sh. Retry binding a probe socket until the port is free,
    then hand off to Flask's own bind.
    """
    for i in range(attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            s.close()
            return
        except OSError:
            s.close()
            if i == attempts - 1:
                return
            time.sleep(delay)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    _bind_with_retry("0.0.0.0", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
