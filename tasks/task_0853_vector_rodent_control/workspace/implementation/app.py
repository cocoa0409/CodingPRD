"""Vector & Rodent Control Program API -- entry point.

Storage is in-memory only and starts EMPTY on every boot: no entity is seeded,
preloaded or hardcoded at start-up. Tests build all state through the API.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_complaints
import routes_inspections
import routes_invoices
import routes_orders
import routes_registry
import routes_reports
import routes_stations
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

app.register_blueprint(routes_registry.bp)
app.register_blueprint(routes_complaints.bp)
app.register_blueprint(routes_inspections.bp)
app.register_blueprint(routes_orders.bp)
app.register_blueprint(routes_stations.bp)
app.register_blueprint(routes_invoices.bp)
app.register_blueprint(routes_reports.bp)

_lock = threading.RLock()


@app.before_request
def _acquire():
    _lock.acquire()


@app.teardown_request
def _release(exc=None):
    try:
        _lock.release()
    except RuntimeError:
        pass


@app.after_request
def _no_keepalive(response):
    # werkzeug's keep-alive handling is a known source of RemoteDisconnected
    # flakiness under the per-test-server harness; close each connection.
    response.headers["Connection"] = "close"
    return response


@app.errorhandler(ApiError)
def _api_error(exc):
    return envelope.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        return envelope.error("ERR_NOT_FOUND", "No such route.", 404)
    if exc.code == 405:
        return envelope.error("ERR_NOT_FOUND", "Method not allowed for this route.", 405)
    if exc.code == 400:
        return envelope.error("ERR_VALIDATION", "The request could not be parsed.", 400)
    return envelope.error("ERR_VALIDATION", exc.description or "Request failed.", exc.code or 500)


@app.errorhandler(Exception)
def _unhandled(exc):
    app.logger.exception("unhandled error")
    return envelope.error("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
