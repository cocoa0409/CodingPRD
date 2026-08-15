"""Beauty & Salon Professional Distribution API — Flask entry point.

Implements PRD.md exactly. All state in-memory (db.store). Logical clock starts at
2026-08-01T00:00:00Z and advances only via POST /api/_clock/set_current_utc.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors as E
import response as R
from routes import register_routes

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(E.ApiError)
def handle_api_error(err):
    return R.error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(_):
    return R.error_response("ERR_NOT_FOUND", 404, "Route not found")


@app.errorhandler(405)
def handle_405(_):
    return R.error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, E.ApiError):
        return R.error_response(err.error_id, err.http_status, err.message)
    if isinstance(err, HTTPException):
        return R.error_response("ERR_INVALID_REQUEST", err.code or 400, err.description)
    return R.error_response("ERR_INVALID_REQUEST", 400, str(err))


register_routes(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
