"""Payroll Tax Amendment & Wage Statement Correction API.

Flask application factory + entry point.  Storage is in-memory only and starts
completely empty on every boot; the logical clock starts at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from common import ApiError, error_response
from routes import amendments, cases, clock, evidence, notices, reference
from routes import remediations, repayments, statements

BLUEPRINTS = (
    clock.bp,
    reference.bp,
    evidence.bp,
    cases.bp,
    amendments.bp,
    statements.bp,
    repayments.bp,
    notices.bp,
    remediations.bp,
)


def _at(error_id, message, http_status):
    """An ApiError carrying an explicit HTTP status (for non-catalogued failures)."""
    err = ApiError(error_id, message)
    err.http_status = http_status
    return err


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response(_at("ERR_ROUTE_NOT_FOUND", "no such route", 404))

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response(_at("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405))

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 400:
            return error_response(ApiError("ERR_INVALID_REQUEST", "malformed request body"))
        return error_response(ApiError("ERR_INVALID_REQUEST", err.description or "bad request"))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unhandled error")
        return error_response(_at("ERR_INTERNAL", str(err) or "internal error", 500))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
