"""Student Loan Repayment Match Benefit API -- Flask application factory.

Storage is in-memory only and starts EMPTY on every boot: no seeding, no
preloading, no hardcoded entity data, no file or database persistence.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import (allocations, amendments, clock, employees, funding, loans,
                    payroll, plan_years, tests_acp)

BLUEPRINTS = (
    plan_years.bp,
    amendments.bp,
    employees.bp,
    payroll.bp,
    loans.bp,
    allocations.bp,
    funding.bp,
    tests_acp.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(404)
    def _handle_404(_exc):
        return error_response(ApiError("ERR_RECORD_NOT_FOUND",
                                       "resource not found"))

    @app.errorhandler(405)
    def _handle_405(_exc):
        return error_response(ApiError("ERR_INVALID_REQUEST",
                                       "method not allowed"))

    @app.errorhandler(400)
    def _handle_400(_exc):
        return error_response(ApiError("ERR_INVALID_REQUEST",
                                       "malformed request"))

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc)
        app.logger.exception("unhandled error: %s", exc)
        return error_response(ApiError("ERR_INVALID_REQUEST", str(exc)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
