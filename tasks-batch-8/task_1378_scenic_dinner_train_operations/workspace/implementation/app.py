"""Scenic Dinner Train Operations API — Flask entry point.

In-memory stores only (db.py); the process boots empty on every invocation with
the logical clock fixed at 2026-08-01T00:00:00Z until
POST /railroad/_clock/set_current_utc moves it (which also runs the sweep)."""
import os

from flask import Flask

from envelope import error_resp
from errors import ApiError, ERR_NOT_FOUND
from routes import all_blueprints

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in all_blueprints():
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_resp(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_resp(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_resp(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_resp("ERR_INTERNAL", "Internal server error: %s" % err, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
