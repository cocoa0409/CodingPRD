"""Mosquito Abatement District API — Flask entry point.

Storage is in-memory only and starts EMPTY on every boot; nothing is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import api_area
import api_lab
import api_notification
import api_plan
import api_product
import api_request
import api_route
from common import ApiError, error_response

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(api_request.bp)
app.register_blueprint(api_area.bp)
app.register_blueprint(api_lab.bp)
app.register_blueprint(api_product.bp)
app.register_blueprint(api_plan.bp)
app.register_blueprint(api_route.bp)
app.register_blueprint(api_notification.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 404:
        return error_response("ERR_NOT_FOUND", 404, "The requested path does not exist.")
    if exc.code == 405:
        return error_response("ERR_METHOD_NOT_ALLOWED", 405,
                              "The method is not allowed for this path.")
    if exc.code and 400 <= exc.code < 500:
        return error_response("ERR_VALIDATION", 422, exc.description or "Bad request.")
    return error_response("ERR_INTERNAL", 500, "Internal server error.")


@app.errorhandler(Exception)
def handle_unexpected(exc):  # pragma: no cover - safety net
    return error_response("ERR_INTERNAL", 500, "Internal server error: %s" % exc)


@app.after_request
def close_connection(response):
    # werkzeug keep-alive causes intermittent RemoteDisconnected errors under
    # per-test-server isolation; close every connection explicitly.
    response.headers["Connection"] = "close"
    return response


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
