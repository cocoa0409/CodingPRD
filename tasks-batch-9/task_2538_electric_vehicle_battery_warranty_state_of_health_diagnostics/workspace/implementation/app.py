"""EV Battery Warranty & State-of-Health Diagnostics API -- entry point.

Storage is in-memory only and the store starts empty on every boot: no entity
is seeded, preloaded or hardcoded here. Every record is created by clients
through the declared endpoints.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from common import LOCK, ApiError, error_body
import routes_assess
import routes_campaign
import routes_claim
import routes_dispute
import routes_master
import routes_ship
import routes_thermal

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_master, routes_assess, routes_claim, routes_thermal,
               routes_campaign, routes_dispute, routes_ship):
    app.register_blueprint(module.bp)


@app.before_request
def _acquire():
    LOCK.acquire()


@app.teardown_request
def _release(exc=None):
    try:
        LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        return jsonify(error_body("ERR_NOT_FOUND", "No such route.")), 404
    if exc.code == 405:
        return jsonify(error_body("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed on this route.")), 405
    if exc.code and exc.code < 500:
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  exc.description or "Bad request.")), exc.code
    return jsonify(error_body("ERR_INTERNAL", "Internal server error.")), 500


@app.errorhandler(Exception)
def _unhandled(exc):
    return jsonify(error_body("ERR_INTERNAL", "Internal server error: %s" % exc)), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
