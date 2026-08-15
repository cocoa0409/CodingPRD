"""Fireworks Display Ops API — entry point.

Flask app: registers blueprints, error handlers, and a per-request lock.
Listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""

import os
import threading

from flask import Flask

from errors import ApiError
from response import error_body

app = Flask(__name__)
app.json.sort_keys = False

# Serialize requests: the store is plain dicts and correctness under the
# harness's concurrent stability sweeps matters more than throughput.
_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    # URL-matching failures (404/405) skip before_request, so the lock may not
    # be held here; releasing an unacquired RLock raises RuntimeError.
    try:
        _LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(e):
    return error_body(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _not_found(e):
    return error_body("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_body("ERR_NOT_FOUND", "method not allowed on this path", 404)


@app.errorhandler(Exception)
def _unhandled(e):
    return error_body("ERR_VALIDATION", f"unhandled error: {e}", 400)


from routes_operators import bp as operators_bp
from routes_displays import bp as displays_bp
from routes_permits import bp as permits_bp
from routes_inventory import bp as inventory_bp
from routes_ops import bp as ops_bp

app.register_blueprint(operators_bp)
app.register_blueprint(displays_bp)
app.register_blueprint(permits_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(ops_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
