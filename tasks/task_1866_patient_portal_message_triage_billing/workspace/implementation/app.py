"""Patient Portal Inbox API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from routes import admin, messages, billing

app = Flask(__name__)

app.register_blueprint(admin.bp)
app.register_blueprint(messages.bp)
app.register_blueprint(billing.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND[0], "resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND[0], "method not allowed", 404)


@app.errorhandler(400)
def handle_400(err):
    return error_response(ERR_INVALID_REQUEST[0], "malformed request", 400)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response(ERR_INVALID_REQUEST[0], "unexpected error: %s" % err, 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
