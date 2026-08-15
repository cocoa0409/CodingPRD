"""LTL Terminal Operations & Linehaul Planning API — Flask entry point.

Boots cleanly from a fresh process on every invocation: all state lives in
process memory (db.store), starts empty, and the logical clock resets to
2026-08-01T00:00:00Z at startup.
"""
import os

from flask import Flask

import middleware
import response
from errors import ApiError
from routes import all_blueprints

app = Flask(__name__)
app.before_request(middleware.authenticate)

for bp in all_blueprints:
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.error(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return response.error(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return response.error(ApiError("ERR_NOT_FOUND", "Resource not found", 405))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return response.error(
        ApiError("ERR_INTERNAL", "Internal error: {}".format(err), 500))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
