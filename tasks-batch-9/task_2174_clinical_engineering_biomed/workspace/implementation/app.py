"""Clinical Engineering & Biomedical Equipment Management API.

Storage is in-memory only and starts EMPTY on every boot: no seeding, no
preloading, no persistence to disk.
"""
from __future__ import annotations

import os
import sys
import traceback

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from store import store

API_PREFIX = "/clinical-engineering"


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    import routes_core
    import routes_devices
    import routes_pm
    import routes_wo
    import routes_loaner
    import routes_recall
    import routes_contracts

    for module in (routes_core, routes_devices, routes_pm, routes_wo,
                   routes_loaner, routes_recall, routes_contracts):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.before_request
    def _acquire():
        store.lock.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_store_locked", False):
            g._store_locked = False
            try:
                store.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(error: ApiError):
        return envelope.err(error.error_id, error.message, error.http_status, store.now_iso())

    @app.errorhandler(HTTPException)
    def _http_error(error: HTTPException):
        return envelope.err(
            "ERR_INVALID_REQUEST",
            error.description or "Request could not be handled.",
            error.code or 400,
            store.now_iso(),
        )

    @app.errorhandler(Exception)
    def _unhandled(error: Exception):
        traceback.print_exc(file=sys.stderr)
        return envelope.err("ERR_INVALID_REQUEST", str(error), 400, store.now_iso())

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
