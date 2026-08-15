"""HR Case Management & Employee Relations API — Flask entry point.

All endpoints are mounted under the /er prefix. The store is in-memory and
starts empty on every boot; all time-dependent behavior reads from the logical
clock (default 2026-08-01T00:00:00Z), never the wall clock.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    from routes import (
        clock, employees, investigators, intake_channels, holidays, cases,
        interviews, evidence, credibility, findings, notices, trends, packages,
    )
    for mod in (
        clock, employees, investigators, intake_channels, holidays, cases,
        interviews, evidence, credibility, findings, notices, trends, packages,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST",
                              f"unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
