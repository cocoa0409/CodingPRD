"""LTL freight classification and density-based reclassification service.

Boots with a completely empty in-memory store on every process start: no seed data,
no disk persistence, and a logical clock pinned to 2026-08-01T00:00:00Z.
"""
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import clock
import response
from errors import ApiError
from routes import captures, core, corrections, pricing, repricing, shipments

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    clock.reset()

    for blueprint in (
        core.bp,
        pricing.bp,
        shipments.bp,
        captures.bp,
        corrections.bp,
        repricing.bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _serialize_requests():
        _LOCK.acquire()
        g._locked = True
        g._touched = set()

    @app.teardown_request
    def _release(_exception=None):
        if g.pop("_locked", False):
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error("ERR_INVALID_REQUEST", "Unknown route.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return response.error("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return response.error(
            "ERR_INVALID_REQUEST", exc.description or "Request could not be handled.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
