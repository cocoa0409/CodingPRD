"""Entry point: Flask app, global lock, auth, error handlers, route registry."""

import os

from flask import Flask, g

from db import lock
from errors import ApiError, ERR_NOT_FOUND
from middleware import authenticate
from util import respond_error
from routes import register_routes

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _before():
    lock.acquire()
    g._lock_held = True
    g.dirty = set()
    authenticate()  # pipeline step 1 for every endpoint


@app.teardown_request
def _teardown(exc):
    if getattr(g, "_lock_held", False):
        g._lock_held = False
        lock.release()


@app.errorhandler(ApiError)
def _api_error(e):
    return respond_error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _not_found(e):
    return respond_error(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def _method_not_allowed(e):
    return respond_error(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def _internal(e):
    return respond_error("ERR_INTERNAL", 500, "Internal server error")


register_routes(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
