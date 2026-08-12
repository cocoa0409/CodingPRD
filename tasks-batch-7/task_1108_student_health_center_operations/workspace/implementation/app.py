"""Student Health Center API -- Flask entry point.

Registers the three route blueprints (60 endpoints under /shc), maps ApiError
to the standard error envelope, and serves 0.0.0.0:$PORT (default 10000) in
the foreground. Storage is in-memory only and starts empty on every boot.
"""
import os

from flask import Flask
from werkzeug.exceptions import NotFound, MethodNotAllowed

from helpers import ApiError, envelope_error
from routes_a import bp_a
from routes_b import bp_b
from routes_c import bp_c

app = Flask(__name__, static_folder=None)
app.register_blueprint(bp_a)
app.register_blueprint(bp_b)
app.register_blueprint(bp_c)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return envelope_error(e.error_id, e.status, e.message)


@app.errorhandler(NotFound)
def handle_not_found(e):
    return envelope_error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(MethodNotAllowed)
def handle_method_not_allowed(e):
    return envelope_error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    return envelope_error("ERR_INVALID_REQUEST", 400, "Malformed request")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
