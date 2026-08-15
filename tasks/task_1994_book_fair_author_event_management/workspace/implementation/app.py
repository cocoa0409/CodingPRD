"""Flask entry point: app creation, error handlers, route registration."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


class _LockMiddleware:
    """Serialize all requests through one re-entrant lock."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with db.lock:
            return self.wsgi_app(environ, start_response)


app.wsgi_app = _LockMiddleware(app.wsgi_app)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    if isinstance(err, HTTPException):
        status = err.code or 500
        error_id = "ERR_NOT_FOUND" if status == 404 else "ERR_INTERNAL"
        return error_response(ApiError(error_id, status, err.name))
    return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))


import routes_core
import routes_negotiation
import routes_inventory
import routes_signing
import routes_finance

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_negotiation.bp)
app.register_blueprint(routes_inventory.bp)
app.register_blueprint(routes_signing.bp)
app.register_blueprint(routes_finance.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
