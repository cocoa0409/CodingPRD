"""Weigh Station Bypass & Fleet Compliance API — Flask entry point.

In-memory only; the store starts empty on every boot. Logical clock defaults
to 2026-08-01T00:00:00Z (PRD 2.4).
"""
import os

from flask import Flask

from errors import ApiError
from response import err
from routes import register_all

app = Flask(__name__)
register_all(app)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_not_found(_e):
    return err("ERR_NOT_FOUND", 404, "route not found")


@app.errorhandler(405)
def handle_method_not_allowed(_e):
    return err("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed for this route")


@app.errorhandler(Exception)
def handle_unexpected(e):
    return err("ERR_INTERNAL", 500, f"unexpected error: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
