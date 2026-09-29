"""Lateral Partner Hiring & Portable Business Diligence API.

Flask entry point. Storage is in-memory only and starts completely empty:
no entity data is seeded, preloaded or hardcoded anywhere.
"""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.book import bp as book_bp
from routes.candidates import bp as candidates_bp
from routes.config import bp as config_bp
from routes.conflicts import bp as conflicts_bp
from routes.integration import bp as integration_bp
from routes.offers import bp as offers_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

# One request at a time: every handler mutates the shared store, and each
# request must be atomic (PRD 2.9 -- a rejected request writes nothing).
_LOCK = threading.RLock()

for blueprint in (config_bp, candidates_bp, book_bp, conflicts_bp, offers_bp,
                  integration_bp):
    app.register_blueprint(blueprint)


@app.before_request
def _acquire():
    _LOCK.acquire()
    g._store_lock_held = True


@app.teardown_request
def _release(_exc=None):
    if g.pop("_store_lock_held", False):
        try:
            _LOCK.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _not_found(_exc):
    return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)


@app.errorhandler(405)
def _method_not_allowed(_exc):
    return error_response("ERR_INVALID_REQUEST",
                          "Method not allowed for this route.", 405)


@app.errorhandler(HTTPException)
def _http_exception(exc):
    if exc.code == 400:
        return error_response("ERR_INVALID_REQUEST",
                              "The request could not be parsed.", 400)
    return error_response("ERR_INVALID_REQUEST", exc.description or "Error.",
                          exc.code or 500)


@app.errorhandler(Exception)
def _unhandled(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    app.logger.exception("unhandled error: %s", exc)
    return error_response("ERR_INVALID_REQUEST", "Internal server error.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
