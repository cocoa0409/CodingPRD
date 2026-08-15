"""Scenic Shop Fabrication API — entry point.

In-memory store; every process start boots with empty state and the logical
clock reading 2026-08-01T00:00:00Z.
"""
import os
import threading

from flask import Flask

from core import ApiError, error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize requests within this process (single-writer simplicity).
_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        _LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def _handle_404(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def _handle_405(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    app.logger.exception("unexpected error")
    return error_response("ERR_INTERNAL", 500, "Internal server error")


import routes_commercial  # noqa: E402
import routes_production  # noqa: E402

app.register_blueprint(routes_commercial.bp)
app.register_blueprint(routes_production.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
