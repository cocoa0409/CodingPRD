"""Entry point: Flask app, error handlers, route registration.

Runs on 0.0.0.0:$PORT (default 10000). In-memory store only — nothing is
seeded at startup; every entity is created via the API surface.
"""

import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response

from routes import (
    clock,
    trust_funds,
    employers,
    apprentices,
    contribution_reports,
    classes,
    enrollments,
    pay_claims,
    funding_allocations,
    equipment_purchases,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock.bp,
        trust_funds.bp,
        employers.bp,
        apprentices.bp,
        contribution_reports.bp,
        classes.bp,
        enrollments.bp,
        pay_claims.bp,
        funding_allocations.bp,
        equipment_purchases.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
