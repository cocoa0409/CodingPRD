"""SFSP Sponsorship & Meal Sites API.

A single-process Flask application whose entire state lives in memory (see
``db.py``).  Nothing is seeded at import time: every boot starts empty, with the
logical clock at 2026-08-01T00:00:00Z, and all state is built by callers through
the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import advances, claims, clock, corrective_actions, days
from routes import budgets, sites, sponsors, visits


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        sponsors,
        budgets,
        advances,
        sites,
        days,
        visits,
        corrective_actions,
        claims,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if error.code == 405:
            return response.error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed for this path.",
                405,
            )
        if error.code and 400 <= error.code < 500:
            return response.error_response(
                "ERR_INVALID_REQUEST", error.description or "Malformed request.", 400
            )
        return response.error_response(
            "ERR_INTERNAL", "An unexpected error occurred.", 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):  # pragma: no cover - safety net
        return response.error_response(
            "ERR_INTERNAL", "An unexpected error occurred: %s" % error, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
