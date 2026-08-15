"""Peer Support Groups API — entry point.

In-memory only: all state lives in module-level dicts (see db.py). Every
start.sh re-invocation boots a completely fresh store. The logical clock
defaults to 2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from util import error_response
from routes_core import register_core
from routes_ops import register_ops
from routes_incidents import register_incidents

app = Flask(__name__)
app.url_map.strict_slashes = False

register_core(app)
register_ops(app)
register_incidents(app)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_):
    return error_response(ApiError(ERR_NOT_FOUND[0], "Resource not found",
                                   ERR_NOT_FOUND[1]))


@app.errorhandler(405)
def handle_405(_):
    return error_response(ApiError(ERR_NOT_FOUND[0], "Method not allowed",
                                   ERR_NOT_FOUND[1]))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response(ApiError(ERR_VALIDATION[0], str(err),
                                   ERR_VALIDATION[1]))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
