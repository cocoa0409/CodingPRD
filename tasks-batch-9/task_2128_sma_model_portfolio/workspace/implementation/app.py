"""SMA Model Delivery API — entry point.

The in-memory store starts EMPTY on every boot; nothing is seeded here or
anywhere else.  Every entity a caller needs is built through the declared API.
"""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from core import (
    ApiError, DEFAULT_CLOCK, ROLE_PLATFORM_ADMIN, authenticate, body_json, db,
    error_response, fmt_dt, ok, parse_dt, require_roles,
)
from routes.catalog import bp as catalog_bp
from routes.models import bp as models_bp
from routes.accounts import bp as accounts_bp
from routes.trading import bp as trading_bp
from routes.harvest import bp as harvest_bp
from routes.billing import bp as billing_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
try:
    app.json.sort_keys = False
except Exception:  # pragma: no cover
    pass


# Requests are serialized so that concurrent writes against the in-memory
# store cannot interleave; the optimistic-concurrency rules of PRD 2.7 are the
# only mechanism that may reject a competing write.
_REQUEST_LOCK = threading.RLock()


@app.before_request
def _before_request():
    _REQUEST_LOCK.acquire()
    g.lock_held = True
    g.touched = set()
    authenticate()


@app.teardown_request
def _teardown_request(exc=None):
    if getattr(g, "lock_held", False):
        g.lock_held = False
        try:
            _REQUEST_LOCK.release()
        except RuntimeError:  # pragma: no cover
            pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def _handle_http_error(err):
    if err.code == 405:
        return error_response(ApiError("ERR_INVALID_REQUEST",
                                       "Method not allowed for this resource.", 405))
    if err.code == 404:
        return error_response(ApiError("ERR_INVALID_REQUEST",
                                       "The requested resource does not exist.", 404))
    return error_response(ApiError("ERR_INVALID_REQUEST", str(err.description),
                                   err.code or 400))


@app.errorhandler(Exception)
def _handle_unexpected(err):  # pragma: no cover - defensive
    app.logger.exception("unhandled error")
    return error_response(ApiError("ERR_INVALID_REQUEST", "Internal server error.", 500))


# --------------------------------------------------------- Logical clock ---
@app.post("/_clock/set_current_utc")
@require_roles(ROLE_PLATFORM_ADMIN)
def set_current_utc():
    body = body_json()
    raw = body.get("to_iso8601")
    parsed = parse_dt(raw) if raw is not None else None
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO-8601 instant.")
    db.clock = parsed
    return ok({"current_utc": fmt_dt(db.clock)})


app.register_blueprint(catalog_bp)
app.register_blueprint(models_bp)
app.register_blueprint(accounts_bp)
app.register_blueprint(trading_bp)
app.register_blueprint(harvest_bp)
app.register_blueprint(billing_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
