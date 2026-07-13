"""Dev Shop Delivery API — entry point.

The in-memory store starts EMPTY on every boot. No entity is ever seeded:
every client, engagement, sprint, ticket, invoice etc. is constructed by the
caller through the declared endpoints.
"""
import errno
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify
from werkzeug.serving import make_server

from core import ApiError, error_response
from routes.engagements import bp as engagements_bp
from routes.delivery import bp as delivery_bp
from routes.scope import bp as scope_bp
from routes.billing import bp as billing_bp
from routes.support import bp as support_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

app.register_blueprint(engagements_bp)
app.register_blueprint(delivery_bp)
app.register_blueprint(scope_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(support_bp)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _handle_404(_e):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Unknown route."))


@app.errorhandler(405)
def _handle_405(_e):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed."))


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    app.logger.exception(e)
    return jsonify({"error_id": "ERR_INTERNAL", "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    # The harness reserves $PORT in a registry but holds no socket on it, and the
    # reserved port sits inside the OS ephemeral range. A concurrent outbound
    # connection can therefore occupy it in the gap before we bind. Retry through
    # that transient window rather than dying on the first EADDRINUSE.
    deadline = time.monotonic() + 30.0
    while True:
        try:
            server = make_server("0.0.0.0", port, app, threaded=True)
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE or time.monotonic() >= deadline:
                raise
            time.sleep(0.2)

    server.serve_forever()
