"""Repertory Cinema Programming & Rights Clearance API.

Storage is in-memory only and starts completely empty on every boot: no entity
is seeded, preloaded or hardcoded anywhere in this process.
"""
import os
import sys
import traceback

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.bookings import bp as bookings_bp
from routes.catalog import bp as catalog_bp
from routes.clearances import bp as clearances_bp
from routes.events import bp as events_bp
from routes.members import bp as members_bp
from routes.orders import bp as orders_bp
from routes.settlements import bp as settlements_bp
from routes.showtimes import bp as showtimes_bp
from routes.tech import bp as tech_bp
from store import db

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (catalog_bp, bookings_bp, clearances_bp, tech_bp, showtimes_bp,
                  events_bp, orders_bp, members_bp, settlements_bp):
    app.register_blueprint(blueprint)


@app.before_request
def _serialize_requests():
    """One in-memory world, one writer at a time."""
    db.lock.acquire()
    g._holds_store_lock = True


@app.teardown_request
def _release_lock(exc=None):
    if g.pop("_holds_store_lock", False):
        try:
            db.lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(err):
    return error_response("ERR_INVALID_REQUEST", err.description or "Invalid request.",
                          err.code or 400)


@app.errorhandler(Exception)
def _handle_unexpected(err):
    traceback.print_exc(file=sys.stderr)
    return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % err, 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
