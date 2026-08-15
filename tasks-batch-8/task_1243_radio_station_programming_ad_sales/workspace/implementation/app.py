"""Radio Station Programming & Ad Sales API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding). Binds
0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask, jsonify

from helpers import ApiError, error_body

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

import store


@app.before_request
def _acquire_store():
    # Serialize requests: multi-step operations (booking + preemption
    # cascade, as-run sweep, affidavit repricing) must be atomic.
    store._lock.acquire()


@app.teardown_request
def _release_store(_exc):
    try:
        store._lock.release()
    except RuntimeError:
        pass

import routes_core
import routes_trade
import routes_orders
import routes_logs
import routes_spots
import routes_endorsements

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_trade.bp)
app.register_blueprint(routes_orders.bp)
app.register_blueprint(routes_logs.bp)
app.register_blueprint(routes_spots.bp)
app.register_blueprint(routes_endorsements.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    body, status = error_body(exc.error_id, exc.message)
    return jsonify(body), status


@app.errorhandler(404)
def handle_not_found(_exc):
    body, status = error_body("ERR_NOT_FOUND", "Resource does not exist")
    return jsonify(body), status


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    body, status = error_body("ERR_NOT_FOUND", "Route does not exist")
    return jsonify(body), status


@app.errorhandler(Exception)
def handle_unexpected(exc):
    # Never leak a bare 500 HTML page; surface as a bad request envelope.
    body, status = error_body("ERR_BAD_REQUEST", f"Malformed request: {exc}")
    return jsonify(body), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
