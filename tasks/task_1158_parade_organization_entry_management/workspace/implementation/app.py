"""Parade Organization API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. The in-memory store
starts empty on every boot; nothing is seeded at startup.
"""
import os

from flask import Flask

from errors import ApiError
from util import respond_error

import routes_parades
import routes_permits
import routes_entries
import routes_ops
import routes_judging
import routes_sponsors

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_parades.bp)
app.register_blueprint(routes_permits.bp)
app.register_blueprint(routes_entries.bp)
app.register_blueprint(routes_ops.bp)
app.register_blueprint(routes_judging.bp)
app.register_blueprint(routes_sponsors.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return respond_error(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return respond_error(ApiError("ERR_VALIDATION", 404, "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return respond_error(ApiError("ERR_VALIDATION", 405, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return respond_error(ApiError("ERR_VALIDATION", 500, f"Internal error: {err}"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
