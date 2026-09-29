"""Champion Home Builders installation network API.

Entry point: registers the blueprints, installs the error handlers that emit the
PRD section 2.2 error envelope, and runs the development server in the
foreground on 0.0.0.0:$PORT. The store is in-memory and starts EMPTY on every
boot -- nothing is seeded here or anywhere else.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes_claims
import routes_orders
import routes_partners
import routes_set
import routes_transport
from envelope import error_response
from errors import ERROR_HTTP, ApiError, message_for
from guards import authenticate

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False


@app.before_request
def _before():
    g.touched_rows = set()
    # Priority 1 runs before body parsing and before path resolution.
    authenticate()


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        error_id = "ERR_NOT_FOUND"
    elif exc.code == 405:
        error_id = "ERR_METHOD_NOT_ALLOWED"
    elif exc.code == 400:
        # A malformed JSON payload is a shape failure (priority 3).
        error_id = "ERR_INVALID_REQUEST"
    else:
        error_id = "ERR_INTERNAL"
    status = ERROR_HTTP.get(error_id, exc.code or 500)
    return error_response(error_id, message_for(error_id), status)


@app.errorhandler(Exception)
def _unexpected(exc):
    app.logger.exception("unhandled error: %s", exc)
    return error_response("ERR_INTERNAL", message_for("ERR_INTERNAL"), 500)


for blueprint in (
    routes_partners.bp,
    routes_orders.bp,
    routes_transport.bp,
    routes_set.bp,
    routes_claims.bp,
):
    app.register_blueprint(blueprint)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
