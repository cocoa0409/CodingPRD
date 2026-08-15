"""Patient Financial Clearance API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store is in-memory and starts empty
on every boot; the logical clock starts at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

from db import db
from errors import ApiError, ERR_NOT_FOUND
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_config
    import routes_patients
    import routes_cases
    import routes_estimates
    import routes_authorizations
    import routes_plans
    import routes_deposits
    import routes_variance
    import routes_escalations
    import routes_clock

    for module in (
        routes_config,
        routes_patients,
        routes_cases,
        routes_estimates,
        routes_authorizations,
        routes_plans,
        routes_deposits,
        routes_variance,
        routes_escalations,
        routes_clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", "internal server error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
