"""Enterprise Risk Register API — entry point.

Storage is in-memory only (module-level dicts). Every fresh process starts
with a completely empty store; the logical clock starts at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import register_all

app = Flask(__name__)
app.url_map.strict_slashes = False

register_all(app)


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e.error_id, e.message, e.status)


@app.errorhandler(404)
def _not_found(_e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _method_not_allowed(_e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 405)


@app.errorhandler(Exception)
def _unhandled(e):
    return error_response("ERR_INTERNAL", str(e), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
