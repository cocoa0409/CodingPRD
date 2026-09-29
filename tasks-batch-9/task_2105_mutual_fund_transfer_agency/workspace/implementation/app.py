"""Mutual Fund Transfer Agency & NAV Processing API."""
import os
import traceback
from decimal import Decimal

from flask import Flask, g
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from routes import (accounts, bluesky, cases, clock_routes, distributions, funds,
                    navs, plans, positions, recons, trades)


class DecimalJSONProvider(DefaultJSONProvider):
    """Insurance: render any stray Decimal at its own precision."""

    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            return float(value)
        return DefaultJSONProvider.default(value)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.json = DecimalJSONProvider(app)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock_routes.bp)
    app.register_blueprint(funds.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(positions.bp)
    app.register_blueprint(bluesky.bp)
    app.register_blueprint(navs.bp)
    app.register_blueprint(trades.bp)
    app.register_blueprint(distributions.bp)
    app.register_blueprint(plans.bp)
    app.register_blueprint(cases.bp)
    app.register_blueprint(recons.bp)

    @app.before_request
    def _acquire():
        db.lock.acquire()
        g._holds_lock = True

    @app.teardown_request
    def _release(exception=None):
        if getattr(g, "_holds_lock", False):
            g._holds_lock = False
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return response.error("ERR_NOT_FOUND", "The requested route does not exist.", 404)
        if error.code == 405:
            return response.error("ERR_METHOD_NOT_ALLOWED",
                                  "The method is not allowed for this route.", 405)
        return response.error("ERR_INVALID_REQUEST", error.description or "Invalid request.",
                              error.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(error):
        traceback.print_exc()
        return response.error("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
