"""Rebuilt Salvage Vehicle Inspection & Title Branding — REST API.

Storage is in-memory only and starts completely empty on every boot: no entity
is ever seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from routes.appeals import bp as appeals_bp
from routes.applications import bp as applications_bp
from routes.clock import bp as clock_bp
from routes.fraud import bp as fraud_bp
from routes.inspections import bp as inspections_bp
from routes.reads import bp as reads_bp
from routes.registry import bp as registry_bp
from routes.titles import bp as titles_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for blueprint in (
    reads_bp,
    registry_bp,
    titles_bp,
    applications_bp,
    inspections_bp,
    appeals_bp,
    fraud_bp,
    clock_bp,
):
    app.register_blueprint(blueprint)


@app.before_request
def _serialise_requests():
    # One request at a time keeps every derived counter deterministic.
    db.request_lock.acquire()
    g._holds_lock = True


@app.teardown_request
def _release_lock(exception=None):
    if getattr(g, "_holds_lock", False):
        g._holds_lock = False
        try:
            db.request_lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    status = exc.code or 500
    if status == 404:
        return response.error("ERR_INVALID_REQUEST", "No such route.", 404)
    if status == 405:
        return response.error("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)
    return response.error("ERR_INVALID_REQUEST", exc.description or "Request could not be processed.", status)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    return response.error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
