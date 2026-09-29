"""Guitar factory operations API.

Entry point: blueprint registration, the logical shop clock and the error
handlers that render every failure in the envelope of PRD 2.2.  Storage is
in-memory only and starts completely empty on every boot.
"""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import store
import validate as v
from envelope import error_response, object_response
from errors import ApiError
from routes.billets import bp as billets_bp
from routes.catalog import bp as catalog_bp
from routes.components import bp as components_bp
from routes.exports import bp as exports_bp
from routes.finish import bp as finish_bp
from routes.inspections import bp as inspections_bp
from routes.lots import bp as lots_bp
from routes.orders import bp as orders_bp
from routes.rooms import bp as rooms_bp
from routes.service import bp as service_bp
from routes.stations import bp as stations_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (rooms_bp, lots_bp, billets_bp, stations_bp, components_bp,
                  catalog_bp, orders_bp, inspections_bp, finish_bp,
                  service_bp, exports_bp):
    app.register_blueprint(blueprint)


@app.post("/_clock/set_current_utc")
def set_clock():
    """PRD 2.5: the one endpoint that bypasses the authentication rung."""
    body = v.body()
    instant = v.get_ts(body, "current_utc")
    store.set_now(instant)
    return object_response({"current_utc": store.fmt_ts(instant)})


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_exc):
    return error_response("ERR_NOT_FOUND", "no such route", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return error_response("ERR_METHOD_NOT_ALLOWED",
                          "method not allowed on this route", 405)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 400:
        return error_response("ERR_INVALID_REQUEST",
                              "the request body is not valid JSON", 422)
    return error_response("ERR_INVALID_REQUEST",
                          exc.description or "invalid request",
                          exc.code or 422)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    if isinstance(exc, HTTPException):
        return handle_http_exception(exc)
    app.logger.exception("unhandled error on %s %s", request.method,
                         request.path)
    return error_response("ERR_INTERNAL", "internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
