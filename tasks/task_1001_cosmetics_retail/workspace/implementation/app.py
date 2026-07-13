"""Cosmetics & Beauty Retail API — entry point.

Storage is in-memory only and starts EMPTY on every boot: no seeding, no
preloading, no persistence of any kind.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response
from routes.bookings import bp as bookings_bp
from routes.catalog import bp as catalog_bp
from routes.inventory import bp as inventory_bp
from routes.loyalty import bp as loyalty_bp
from routes.orders import bp as orders_bp
from routes.promotions import bp as promotions_bp
from routes.returns import bp as returns_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

# Every request is serialised: the invariants of PRD 2.7 are checked after each
# operation, so operations must not interleave.
_lock = threading.Lock()


@app.before_request
def _acquire_lock():
    _lock.acquire()


@app.teardown_request
def _release_lock(_exc=None):
    try:
        _lock.release()
    except RuntimeError:
        pass


for blueprint in (
    catalog_bp,
    inventory_bp,
    loyalty_bp,
    promotions_bp,
    orders_bp,
    bookings_bp,
    returns_bp,
):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_exception(exc):
    if exc.code == 404:
        return error_response("ERR_NOT_FOUND", "resource not found", 404)
    if exc.code == 405:
        return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)
    if exc.code and exc.code < 500:
        return error_response("ERR_INVALID_REQUEST", exc.description or "bad request", exc.code)
    return error_response("ERR_INTERNAL", exc.description or "internal error", exc.code or 500)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    app.logger.exception("unhandled error: %s", exc)
    return error_response("ERR_INTERNAL", "internal server error", 500)


def _skip_reverse_dns():
    """http.server's server_bind() calls socket.getfqdn() purely to fill in a
    cosmetic server_name.  On hosts whose reverse-DNS is slow that call blocks
    the bind for seconds — and this server is re-launched before every single
    test, so that cost is paid on every reboot.  The value is never used for
    routing, so resolve it trivially."""
    import socket

    socket.getfqdn = lambda name="": name or "localhost"


if __name__ == "__main__":
    _skip_reverse_dns()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
