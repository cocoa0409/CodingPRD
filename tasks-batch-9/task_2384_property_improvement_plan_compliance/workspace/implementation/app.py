"""Property Improvement Plan compliance API.

Everything lives in process memory: the store is a set of plain dicts created
empty at import time (see db.py) and nothing is ever seeded, preloaded or
persisted.  A fresh process therefore always starts with an empty world and a
logical clock reading exactly 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routing
from errors import DEFAULT_MESSAGES, ApiError
from response import error_response

# Importing the route modules is what populates routing.ROUTES.
from routes import (  # noqa: F401
    bookings,
    budgets,
    disputes,
    draws,
    extensions,
    inspections,
    items,
    ledger,
    notices,
    phases,
    plans,
    portfolio,
    punch,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    seen = set()
    for rule, methods, roles, fn in routing.ROUTES:
        endpoint = fn.__name__
        suffix = 1
        while endpoint in seen:
            suffix += 1
            endpoint = "%s_%d" % (fn.__name__, suffix)
        seen.add(endpoint)
        app.add_url_rule(
            rule,
            endpoint,
            routing.make_view(fn, roles),
            methods=list(methods),
        )

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", DEFAULT_MESSAGES.get("ERR_NOT_FOUND", "not found"), 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                DEFAULT_MESSAGES.get("ERR_METHOD_NOT_ALLOWED", "method not allowed"),
                405,
            )
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "malformed request", 422)
        return error_response(
            "ERR_INTERNAL", exc.description or "internal error", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
