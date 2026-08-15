"""Utility EE Rebate API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot;
all state is in-memory and per-process, so per-test-server restarts always
yield a clean slate.
"""
import os

from flask import Flask

from errors import ApiError
from respond import error_body
from routes import ALL_BLUEPRINTS

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_body("ERR_INVALID_REQUEST", "Unknown route", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_body("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Bug-safety net: keep the error envelope shape even on failures.
    return error_body("ERR_INTERNAL", "Internal server error: %s" % err, 500)


for blueprint in ALL_BLUEPRINTS:
    app.register_blueprint(blueprint)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
