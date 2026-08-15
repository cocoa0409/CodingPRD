"""Restaurant Equipment Dealer & Kitchen Design-Build API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Storage is in-memory only; the store is
empty on every boot and nothing is seeded.
"""

from __future__ import annotations

import os
import sys

# Allow `python3 app.py` from this directory with sibling-module imports.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException):
        # Unmatched routes / wrong methods still return the error envelope.
        status = err.code or 500
        error_id = "ERR_NOT_FOUND" if status == 404 else "ERR_INVALID_REQUEST"
        if status >= 500:
            error_id = "ERR_INTERNAL"
        return error_response(error_id, err.description or "HTTP error", status)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    from routes import (
        agencies,
        customers,
        deliveries,
        fabrication,
        filings,
        items,
        layouts,
        projects,
        punch,
        quotes,
        sessions,
        toplevel,
    )

    for module in (
        customers,
        projects,
        layouts,
        items,
        quotes,
        fabrication,
        filings,
        deliveries,
        sessions,
        agencies,
        punch,
        toplevel,
    ):
        app.register_blueprint(module.bp)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
