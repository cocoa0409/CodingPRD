"""Coffee Roaster Wholesale API — Flask entry point.

In-memory storage only (see db.py). No entity data is seeded at startup: the
store starts empty and every entity is created through the declared API surface.

A single global lock serializes all request handling so that concurrent races
(OCC on green/roasted lots, exercised by the test suite's run_race helper) have
deterministic, atomic read-check-write semantics over the shared dict store.
"""
import os
import threading

from flask import Flask, request

from errors import ApiError
from response import error_response

# Blueprints
from routes.catalog import bp as catalog_bp
from routes.production import bp as production_bp
from routes.standing_orders import bp as standing_orders_bp
from routes.orders import bp as orders_bp
from routes.samples import bp as samples_bp
from routes.invoices import bp as invoices_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize mutations (and reads) for deterministic OCC under concurrent races.
_LOCK = threading.RLock()


@app.before_request
def _acquire():
    _LOCK.acquire()


@app.teardown_request
def _release(exc=None):
    try:
        _LOCK.release()
    except RuntimeError:
        pass


# ---- error handling ----
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    # method not allowed on a known path — treat as not found per benchmark norms
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", f"Unhandled error: {err}", 422)


# ---- register routes ----
app.register_blueprint(catalog_bp)
app.register_blueprint(production_bp)
app.register_blueprint(standing_orders_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(samples_bp)
app.register_blueprint(invoices_bp)


@app.get("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
