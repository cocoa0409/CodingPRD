"""OSHA Recordkeeping & Workplace Safety API.

Flask entry point. In-memory store starts empty on every boot; the logical
clock boots at 2026-08-01T00:00:00Z per PRD §2.4 and moves only via
POST /safety/_clock/set_current_utc.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False

    from routes import (clock, companies, establishments, employees, cases,
                        investigations, corrective_actions, summaries,
                        hour_logs, inspections, citations)
    for mod in (clock, companies, establishments, employees, cases,
                investigations, corrective_actions, summaries, hour_logs,
                inspections, citations):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
