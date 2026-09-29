"""State Revenue Forecasting & Reserve Management API — Flask entry point.

Storage is in-memory only (see db.py) and starts completely empty on every boot:
nothing is seeded, preloaded or read from disk.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import actuals, briefings, clock, cycles, funds, items, rounds, sources, withdrawals


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:                                    # keep declaration order in JSON bodies
        app.json.sort_keys = False
    except AttributeError:                  # Flask < 2.3
        app.config["JSON_SORT_KEYS"] = False

    for module in (clock, cycles, sources, items, rounds, funds, withdrawals, actuals, briefings):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "malformed request", 422)
        return error_response("ERR_HTTP_%d" % (exc.code or 500),
                              exc.description or "request failed", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
