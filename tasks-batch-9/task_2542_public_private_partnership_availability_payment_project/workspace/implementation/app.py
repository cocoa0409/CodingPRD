"""PPP availability-payment API — entry point.

The in-memory store starts completely empty on every boot; no entity is seeded,
preloaded or hardcoded anywhere in this process.
"""

import os

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

from db import db
from errors import ApiError
from response import error_body
from routes.concessions import bp as concessions_bp
from routes.deductions import bp as deductions_bp
from routes.drawdown import bp as drawdown_bp
from routes.enforcement import bp as enforcement_bp
from routes.periods import bp as periods_bp
from routes.reads import bp as reads_bp
from routes.relief import bp as relief_bp

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _open_transaction():
    g._touched = set()
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        g._snapshot = db.snapshot()


def _rollback():
    snapshot = getattr(g, "_snapshot", None)
    if snapshot is not None:
        db.restore(snapshot)
        g._snapshot = None


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    _rollback()
    return error_body(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    _rollback()
    status = exc.code or 500
    if status == 404:
        return error_body("ERR_INVALID_REQUEST", "Unknown resource path.", 404)
    return error_body("ERR_INVALID_REQUEST", exc.description or "Bad request.", status)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    _rollback()
    return error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)


for blueprint in (reads_bp, concessions_bp, drawdown_bp, periods_bp, deductions_bp,
                  relief_bp, enforcement_bp):
    app.register_blueprint(blueprint)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
