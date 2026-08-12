"""Entry point: Flask app, error handlers, blueprint registration.

In-memory only — the store starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

import db  # noqa: F401  (module init creates the empty store)
from errors import ApiError
from response import error_response
from routes import (
    clock_routes, coordination, drills, emergency, exams, fieldday, loans,
    members, nets, repeaters, sites,
)

app = Flask(__name__)

for module in (clock_routes, members, sites, repeaters, coordination, nets,
               emergency, drills, fieldday, exams, loans):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response("ERR_NOT_FOUND", 405, "method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, "internal error: %s" % err)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
