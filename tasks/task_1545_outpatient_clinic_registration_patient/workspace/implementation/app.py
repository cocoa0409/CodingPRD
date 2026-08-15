"""Entry point: app wiring, error handlers, server bootstrap."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
from routes import bp
from routes2 import bp2

app = Flask(__name__)
app.url_map.strict_slashes = False
app.register_blueprint(bp)
app.register_blueprint(bp2)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(400)
def handle_400(e):
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, "malformed request"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, HTTPException):
        return error_response(ApiError("ERR_INVALID_REQUEST", e.code or 400, e.name))
    return error_response(ApiError("ERR_INVALID_REQUEST", 500, "internal error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
