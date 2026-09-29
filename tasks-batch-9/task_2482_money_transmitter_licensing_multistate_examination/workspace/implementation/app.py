"""Multistate Money Transmitter Licensing & Examination Platform.

Flask application factory and process entry point. All state lives in the
in-memory ``db`` store of ``db.py``; nothing is persisted and nothing is seeded,
so every fresh process starts with an empty estate and the logical clock at
2026-08-01T00:00:00Z.
"""

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes import (
    applications,
    authorizations,
    call_reports,
    control_persons,
    delegates,
    enforcement,
    exams,
    info_requests,
    investments,
    licensees,
    state_licenses,
    system,
)

BLUEPRINTS = (
    system.bp,
    licensees.bp,
    control_persons.bp,
    applications.bp,
    state_licenses.bp,
    call_reports.bp,
    delegates.bp,
    authorizations.bp,
    investments.bp,
    exams.bp,
    info_requests.bp,
    enforcement.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error("ERR_INVALID_REQUEST", "No such resource path", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error("ERR_INVALID_REQUEST", "Method not allowed for this path", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST", exc.description or "Malformed request", 400)
        return error(
            "ERR_INVALID_REQUEST", exc.description or "Request could not be served", exc.code
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        traceback.print_exc()
        return error("ERR_INVALID_REQUEST", "Unexpected server condition: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
