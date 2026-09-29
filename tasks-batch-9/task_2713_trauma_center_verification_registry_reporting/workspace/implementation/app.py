"""Trauma Verification Registry API — application entry point.

The store is process-local and starts empty on every boot: no seeding, no
preloading, no persistence. The harness relaunches this process through
start.sh before every test, which is what wipes all state.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import begin_request, error_body
from errors import ApiError
from routes import abstractions, cases, centers, config, cycles, pi

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (centers, config, cases, abstractions, pi, cycles):
    app.register_blueprint(module.bp)


@app.before_request
def _before_request():
    begin_request()


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_body(exc.error_id, exc.message), exc.http_status


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 404:
        return error_body("ERR_REFERENCED_RESOURCE_NOT_FOUND", "resource not found"), 404
    if exc.code == 405:
        return error_body("ERR_INVALID_REQUEST", "method not allowed for this path"), 405
    if exc.code in (400, 415):
        return error_body("ERR_INVALID_REQUEST", "malformed request"), 400
    return error_body("ERR_INVALID_REQUEST", exc.description or "request failed"), exc.code or 500


@app.errorhandler(Exception)
def _unhandled(exc):
    return error_body("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
