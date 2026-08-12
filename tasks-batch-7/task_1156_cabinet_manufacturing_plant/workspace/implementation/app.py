"""KCMA Cabinet Manufacturing Plant API — Flask entry point.

Mounts every route group under /kcma, wraps errors in the standard envelope,
and serializes request handling so each request's side effects are atomic.
"""
import os
import threading

from flask import Flask

from errors import ApiError
from util import respond_api_error
import routes_assembly
import routes_catalog
import routes_claims
import routes_finish
import routes_nesting
import routes_orders
import routes_shipping

app = Flask(__name__)

# All side effects are atomic within the triggering request; a process-wide
# lock gives that guarantee even under concurrent clients.
_request_lock = threading.RLock()


@app.before_request
def _acquire_lock():
    _request_lock.acquire()


@app.teardown_request
def _release_lock(exc):
    _request_lock.release()


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return respond_api_error(err)


@app.errorhandler(404)
def _handle_404(err):
    return respond_api_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(err):
    return respond_api_error(ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return respond_api_error(err)
    return respond_api_error(ApiError("ERR_INTERNAL", 500, f"Internal error: {err}"))


for module in (
    routes_catalog,
    routes_orders,
    routes_finish,
    routes_nesting,
    routes_assembly,
    routes_claims,
    routes_shipping,
):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
