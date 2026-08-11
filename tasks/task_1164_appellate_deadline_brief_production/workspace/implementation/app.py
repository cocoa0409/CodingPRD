"""Appellate Deadline & Brief Production Management API.

Flask entry point. In-memory store starts empty on every boot; logical clock
pinned at 2026-05-01T00:00:00Z per PRD §2.5.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False

    from routes import (
        courts, attorneys, cases, events, deadlines, records, transcripts,
        schedules, briefs, toas, motions, filings, arguments, decisions,
        petitions, clock,
    )
    for mod in (courts, attorneys, cases, events, deadlines, records,
                transcripts, schedules, briefs, toas, motions, filings,
                arguments, decisions, petitions, clock):
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
