"""Executive Compensation & Say-on-Pay Disclosure API.

Flask application factory and error plumbing.  All state lives in the
process-local dictionaries of ``db.store``; nothing is persisted, nothing is
seeded, so every boot starts empty with the logical clock at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    awards,
    cda,
    clock,
    companies,
    metrics,
    outreach,
    pay_programs,
    peer_groups,
    restatements,
    screens,
)

BLUEPRINTS = (
    companies.bp,
    peer_groups.bp,
    pay_programs.bp,
    metrics.bp,
    awards.bp,
    cda.bp,
    screens.bp,
    outreach.bp,
    restatements.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "No route matches the requested path.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "The HTTP method is not allowed here.", 405
            )
        if exc.code in (400, 415):
            return error_response(
                "ERR_INVALID_REQUEST", "The request body could not be parsed.", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        app.logger.exception("unhandled error")
        return error_response("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
