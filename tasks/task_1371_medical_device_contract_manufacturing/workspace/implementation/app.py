"""Entry point: Flask app, error handlers, route registration.

Storage is in-memory only (see store.py) - nothing is seeded at startup;
every fresh process boots with an empty store and the logical clock at
2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError

app = Flask(__name__)

import routes_clock
import routes_dmrs
import routes_lines
import routes_lots
import routes_protocols
import routes_quality
import routes_studies
import routes_suppliers

for module in (routes_dmrs, routes_lines, routes_suppliers, routes_protocols,
               routes_studies, routes_lots, routes_quality, routes_clock):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(_):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
