"""Confectionery Plant Production API — entry point.

In-memory only; the store starts empty on every boot and nothing is seeded.
Listens on the PORT env var (default 10000), bound to 0.0.0.0.
"""
import os
import threading

from flask import Flask

from errors import ApiError
from response import error_response

from routes.changeovers import changeovers_bp
from routes.clock import clock_bp
from routes.gift_components import gift_components_bp
from routes.holds import holds_bp
from routes.lines import lines_bp
from routes.lots import lots_bp
from routes.molds import molds_bp
from routes.packaging import packaging_bp
from routes.products import products_bp
from routes.recipes import recipes_bp
from routes.runs import runs_bp
from routes.windows import windows_bp

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

for bp in (products_bp, recipes_bp, gift_components_bp, packaging_bp, molds_bp,
           lines_bp, changeovers_bp, windows_bp, runs_bp, lots_bp, holds_bp,
           clock_bp):
    app.register_blueprint(bp)

# Serialize request handling so interleaved requests cannot observe partial
# cascade states.
_request_lock = threading.RLock()


@app.before_request
def _acquire_lock():
    _request_lock.acquire()


@app.teardown_request
def _release_lock(_exc):
    _request_lock.release()


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found."))


@app.errorhandler(405)
def _handle_405(_err):
    err = ApiError("ERR_NOT_FOUND", "Method not allowed.")
    err.http_status = 405
    return error_response(err)


@app.errorhandler(400)
def _handle_400(_err):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Malformed request."))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    err500 = ApiError("ERR_INVALID_REQUEST", "Internal error: %s" % err)
    err500.http_status = 500
    return error_response(err500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
