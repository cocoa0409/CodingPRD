"""Federated fundraising campaign and allocation service.

Entry point: registers every resource blueprint under the /fundraising prefix
(PRD 4) plus the out-of-band logical-clock endpoint at the server root, and
installs the envelope-shaped error handlers described in PRD 2.2.

The store is in-memory and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded here or anywhere else at import time.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import error_response, ok
from errors import ApiError

from routes import (agencies, campaigns, clock, cycles, employers, panelists,
                    pledges, reports, requests as requests_routes)

API_PREFIX = "/fundraising"

app = Flask(__name__)
app.url_map.strict_slashes = False
try:  # Flask >= 2.3
    app.json.sort_keys = False
except AttributeError:  # pragma: no cover - older Flask
    app.config["JSON_SORT_KEYS"] = False

for blueprint in (
    employers.bp,
    campaigns.bp,
    pledges.bp,
    agencies.bp,
    cycles.bp,
    requests_routes.bp,
    panelists.bp,
    reports.bp,
):
    app.register_blueprint(blueprint, url_prefix=API_PREFIX)

app.register_blueprint(clock.bp)


@app.before_request
def _reset_request_scope():
    g._touched = set()


@app.get("/")
def root():
    """Liveness probe for the harness; not part of the declared API surface."""
    return ok({"service": "fundraising", "status": "ready"})


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    return error_response(
        "ERR_INVALID_REQUEST",
        exc.description or "Request could not be processed.",
        exc.code or 400,
    )


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
