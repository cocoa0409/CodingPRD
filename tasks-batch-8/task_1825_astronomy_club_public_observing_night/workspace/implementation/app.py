"""Astronomy Club Observing API — Flask entry point.

Storage is in-memory only (see store.py). The store starts empty on every boot;
no entity is seeded, preloaded, or hardcoded at startup.
"""
import os

from flask import Flask

from helpers import ApiError, error_response
from routes import ALL_BLUEPRINTS
from store import DB

app = Flask(__name__)
app.json.sort_keys = False

for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


@app.before_request
def _acquire_lock():
    DB.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        DB.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(err):
    return error_response(ApiError(404, "ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(405)
def _handle_405(err):
    return error_response(ApiError(404, "ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    return error_response(ApiError(500, "ERR_INVALID_REQUEST",
                                   "Internal error: %s" % err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
