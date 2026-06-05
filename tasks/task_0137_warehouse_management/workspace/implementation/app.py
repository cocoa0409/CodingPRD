"""Warehouse Management System API — Flask entry point.

In-memory only; empty on every boot. Foreground server reading $PORT, bound to
0.0.0.0, with a defensive bind-retry loop for the parallel restart sweep.
"""
import os
import socket
import sys
import time

from flask import Flask

from errors import ApiError
from response import error_response
from routes.catalog import bp as catalog_bp
from routes.inbound import bp as inbound_bp
from routes.putaway import bp as putaway_bp
from routes.outbound import bp as outbound_bp
from routes.waves import bp as waves_bp
from routes.inventory import bp as inventory_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(inbound_bp)
    app.register_blueprint(putaway_bp)
    app.register_blueprint(outbound_bp)
    app.register_blueprint(waves_bp)
    app.register_blueprint(inventory_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed.")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Surface unexpected failures as a generic invalid-request rather than a
        # bare 500 HTML page, keeping the envelope consistent.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % exc)

    return app


app = create_app()


def _bind_with_retry(host, port, attempts=40, delay=0.25):
    """Defensive bind-retry: during the parallel restart sweep two servers can
    briefly contend the same port. Retry the bind a few times before giving up."""
    last_err = None
    for _ in range(attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.close()
            return
        except OSError as exc:
            last_err = exc
            s.close()
            time.sleep(delay)
    if last_err is not None:
        print("Could not bind %s:%s after retries: %s" % (host, port, last_err),
              file=sys.stderr)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    host = "0.0.0.0"
    _bind_with_retry(host, port)
    app.run(host=host, port=port, threaded=True, use_reloader=False)
