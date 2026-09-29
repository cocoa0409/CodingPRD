"""Urology Procedure Suite API — application entry point.

The store is in-memory and starts empty on every boot: nothing is seeded, preloaded
or hardcoded. Every entity is built by a caller through the declared endpoints.
"""

import os

from flask import Flask

import constants
import response
from errors import ApiError
from routes import antibiotics, cases, recalls, reference, referrals, reprocessing, specimens

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (reference, cases, antibiotics, reprocessing, specimens, recalls, referrals):
    app.register_blueprint(module.bp, url_prefix=constants.API_PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(exc):
    return response.error_response("ERR_INVALID_REQUEST", "The requested path does not exist.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return response.error_response(
        "ERR_INVALID_REQUEST", "The HTTP method is not allowed for this path.", 405
    )


@app.errorhandler(400)
def handle_bad_request(exc):
    return response.error_response("ERR_INVALID_REQUEST", "The request payload is malformed.", 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    app.logger.exception("unhandled error")
    return response.error_response("ERR_INVALID_REQUEST", str(exc), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
