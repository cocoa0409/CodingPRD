"""Trustee Auction Marketplace API — Flask entrypoint.

Storage is entirely in-memory (see db.py) and nothing is ever seeded: a fresh
process starts with every collection empty and the logical clock at
2026-08-01T00:00:00Z.
"""

import os
import sys
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

import util
from errors import ApiError
from routes import register


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    register(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return util.err(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        # Unknown routes and unsupported methods still answer in the envelope.
        return util.err("ERR_INVALID_REQUEST", exc.description or "Invalid request.",
                        exc.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        traceback.print_exc(file=sys.stderr)
        return util.err("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
