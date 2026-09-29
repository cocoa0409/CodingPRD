"""Pro Desk Contractor Account API — Flask entry point.

State lives in process memory only (see db.py) and starts completely empty on
every boot: nothing is seeded, preloaded or read from disk.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.accounts import bp as accounts_bp
from routes.config import bp as config_bp
from routes.finance import bp as finance_bp
from routes.logistics import bp as logistics_bp
from routes.orders import bp as orders_bp
from routes.quotes import bp as quotes_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(logistics_bp)
    app.register_blueprint(finance_bp)

    @app.before_request
    def _init_request():
        # one version bump per record per request (see db.touch)
        g._touched_ids = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "No such resource.", 404)
        if exc.code == 405:
            return response.error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return response.error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error("ERR_INTERNAL", str(exc) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
