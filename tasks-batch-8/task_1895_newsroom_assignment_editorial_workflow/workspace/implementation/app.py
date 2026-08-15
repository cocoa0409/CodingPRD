"""Newsroom Editorial Workflow API — Flask entry point.

In-memory only: all state lives in server.store.STORE inside this process.
Every start.sh invocation boots a fresh, empty store.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from server.blueprint import bp
from server.envelope import err_response
from server.errors import ApiError

# Route modules register against the shared blueprint on import.
from server import (  # noqa: F401
    routes_staff,
    routes_pitches,
    routes_stories,
    routes_assignments,
    routes_slots,
    routes_corrections,
    routes_breaking,
    routes_ops,
)

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        error_id = "ERR_NOT_FOUND" if e.code == 404 else "ERR_INVALID_REQUEST"
        status = e.code if e.code and 400 <= e.code < 600 else 500
        return err_response(error_id, status, e.description or "HTTP error")
    return err_response("ERR_INVALID_REQUEST", 500, "Internal server error")


app.register_blueprint(bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
