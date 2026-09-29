"""Spare Parts Aftermarket API — entry point.

The in-memory store starts empty on every boot; nothing is seeded here.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import envelope
import store
from errors import ApiError

from routes.clock import bp as clock_bp
from routes.parts import bp as parts_bp
from routes.registry import bp as registry_bp
from routes.work_orders import bp as work_orders_bp
from routes.campaigns import bp as campaigns_bp
from routes.pricing import bp as pricing_bp
from routes.replenishment import bp as replenishment_bp
from routes.returns import bp as returns_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for bp in (clock_bp, parts_bp, registry_bp, work_orders_bp, campaigns_bp,
               pricing_bp, replenishment_bp, returns_bp):
        app.register_blueprint(bp)

    # Every request runs under one global lock so that a multi-step mutation
    # (reserve, waterfall, cascade) is atomic against concurrent clients.
    @app.before_request
    def _acquire():
        store.lock().acquire()
        g._store_locked = True

    @app.teardown_request
    def _release(_exc=None):
        if getattr(g, "_store_locked", False):
            g._store_locked = False
            try:
                store.lock().release()
            except RuntimeError:
                pass

    @app.get("/")
    def _root():
        return envelope.ok({"service": "spare-parts-aftermarket"})

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return envelope.error("ERR_INVALID_REQUEST", "Resource not found.", 404)
        if exc.code == 405:
            return envelope.error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code and 400 <= exc.code < 500:
            return envelope.error("ERR_INVALID_REQUEST", exc.description or "Bad request.", exc.code)
        return envelope.error("ERR_INVALID_REQUEST", exc.description or "Server error.", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return envelope.error("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
