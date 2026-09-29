"""Residential Earthquake Coverage & Mitigation Incentive Program API.

Entry point: registers every blueprint under the /eqp prefix, installs the
error handlers that render the PRD's error envelope, and serialises requests so
the cascades stay atomic.  The store starts completely empty on every boot: no
entity is seeded, preloaded or hardcoded here.
"""

import os
import threading
import traceback

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import envelope
import routes_catastrophe
import routes_contractors
import routes_dwellings
import routes_grants
import routes_insurers
import routes_offers
import routes_policies
from errors import ApiError

API_PREFIX = "/eqp"

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for module in (routes_insurers, routes_dwellings, routes_offers, routes_policies,
               routes_grants, routes_contractors, routes_catastrophe):
    app.register_blueprint(module.bp, url_prefix=API_PREFIX)

# One request at a time: every multi-hop cascade must be observed whole.
_LOCK = threading.Lock()


@app.before_request
def _acquire():
    _LOCK.acquire()
    g._holds_lock = True


@app.teardown_request
def _release(exc=None):
    if g.pop("_holds_lock", False):
        _LOCK.release()


@app.errorhandler(ApiError)
def _api_error(exc):
    return envelope.error_response(exc.error_id, exc.message, exc.status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    status = exc.code or 500
    if status == 404:
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "No such resource path.", 404)
    if status == 405:
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "Method not allowed on this path.", 405)
    return envelope.error_response("ERR_INVALID_REQUEST", exc.description or "", status)


@app.errorhandler(Exception)
def _unexpected(exc):
    traceback.print_exc()
    return envelope.error_response(
        "ERR_INVALID_REQUEST", "The request could not be processed.", 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
