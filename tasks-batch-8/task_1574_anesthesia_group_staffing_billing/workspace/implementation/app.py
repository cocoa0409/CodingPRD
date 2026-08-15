"""Anesthesia Group Staffing & Billing API — entry point."""
import os

from flask import Flask

from errors import ApiError
from envelope import err

import routes_core
import routes_rosters
import routes_cases
import routes_calls
import routes_attest
import routes_billing
import routes_audits


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (routes_core.bp, routes_rosters.bp, routes_cases.bp, routes_calls.bp,
               routes_attest.bp, routes_billing.bp, routes_audits.bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return err("ERR_INVALID_REQUEST", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return err("ERR_INVALID_REQUEST", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err(e.error_id, e.http_status, e.message)
        return err("ERR_INVALID_REQUEST", 500, "Internal error: %s" % type(e).__name__)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
