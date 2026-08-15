"""Community Bike Shop & Earn-a-Bike Program API — entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot; the
logical clock starts at exactly 2026-08-01T00:00:00Z and never falls back to
wall time.
"""

import os

from flask import Flask

from errors import ApiError
from response import error
from routes import ops, donors, bikes, parts, volunteers, training, shifts, participants, sales, giveaways, memberships, helmets

app = Flask(__name__)

for module in (ops, donors, bikes, parts, volunteers, training, shifts,
               participants, sales, giveaways, memberships, helmets):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_):
    return error("ERR_NOT_FOUND", "The requested resource does not exist", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_):
    return error("ERR_NOT_FOUND", "The requested resource does not exist", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error(exc.error_id, exc.message, exc.http_status)
    return error("ERR_VALIDATION", "The request could not be processed", 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
