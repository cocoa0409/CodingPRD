"""Non-Traded REIT Fundraising & Repurchase API.

A single Flask process holding every row in memory (see store.py): the store is
empty at boot and nothing is persisted, so relaunching this module is a full
reset.  Requests are serialised on one lock, which keeps the derived-figure
recomputation in PRD §2.10 atomic with respect to concurrent writers.
"""

import os

from flask import Flask, g

import auth
import store
from errors import ApiError, ERROR_STATUS, DEFAULT_MESSAGES
from response import error_response
from routes.investors import bp as investors_bp
from routes.liquidity import bp as liquidity_bp
from routes.navs import bp as navs_bp
from routes.offerings import bp as offerings_bp
from routes.repurchase import bp as repurchase_bp
from routes.subscriptions import bp as subscriptions_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

app.register_blueprint(offerings_bp)
app.register_blueprint(investors_bp)
app.register_blueprint(subscriptions_bp)
app.register_blueprint(navs_bp)
app.register_blueprint(repurchase_bp)
app.register_blueprint(liquidity_bp)


@app.before_request
def _begin():
    store.LOCK.acquire()
    g._holds_lock = True
    auth.authenticate()


@app.teardown_request
def _end(exception=None):
    if getattr(g, "_holds_lock", False):
        g._holds_lock = False
        try:
            store.LOCK.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(404)
def _not_found(error):
    return error_response(
        "ERR_RESOURCE_NOT_FOUND",
        DEFAULT_MESSAGES.get("ERR_RESOURCE_NOT_FOUND", "Not found."),
        ERROR_STATUS["ERR_RESOURCE_NOT_FOUND"])


@app.errorhandler(405)
def _not_allowed(error):
    return error_response("ERR_INVALID_REQUEST",
                          "The HTTP method is not supported for this path.", 400)


@app.errorhandler(400)
def _bad_request(error):
    return error_response("ERR_INVALID_REQUEST",
                          "The request could not be parsed.", 400)


@app.errorhandler(Exception)
def _unhandled(error):
    if isinstance(error, ApiError):
        return _api_error(error)
    app.logger.exception("unhandled error")
    return error_response("ERR_INVALID_REQUEST", str(error) or "Unhandled error.", 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
