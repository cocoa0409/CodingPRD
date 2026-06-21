"""Flask entry point for the 529 College Savings benchmark API.

start.sh runs `python3 app.py`; that binds 0.0.0.0:$PORT (default 10000) and
serves all routes. The in-memory store is fresh on every process boot — the
test harness (`prd-bench-local-run --isolation per-test-server`) relies on
that to give each pytest a clean DB.
"""
from __future__ import annotations

import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_FORBIDDEN
from response import error_response
from routes import register_all


def create_app() -> Flask:
    app = Flask(__name__)
    # We handle our own JSON validation; werkzeug's default 400 is fine but we
    # reshape it via the global handler below.
    app.config["PROPAGATE_EXCEPTIONS"] = False

    register_all(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Werkzeug raises 404 when no route matches the URL — fold into the
        # standard envelope with ERR_NOT_FOUND.
        return error_response(ERR_NOT_FOUND, "route not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(ERR_FORBIDDEN, "method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc: HTTPException):
        if 400 <= (exc.code or 500) < 500:
            return error_response(ERR_INVALID_REQUEST, exc.description or "bad request", exc.code)
        return error_response("ERR_INTERNAL", exc.description or "internal error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):  # pragma: no cover - defensive
        # Last-resort handler; surface as 500 with a placeholder id so tests
        # don't hang waiting for a non-existent response shape.
        return error_response("ERR_INTERNAL", str(exc) or "internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Flask's dev server is sufficient — single-process, blocking, fine for the
    # benchmark which serially restarts the server between tests.
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
