"""Continuing Education & Non-Credit Registration API.

Storage is entirely in-memory and starts empty on every boot: no entity is
seeded, preloaded or hardcoded anywhere in this process.
"""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, LOCK, envelope_error
import routes_catalog
import routes_people
import routes_reg
import routes_flow


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_people.bp)
    app.register_blueprint(routes_reg.bp)
    app.register_blueprint(routes_flow.bp)

    @app.before_request
    def _acquire_lock():
        LOCK.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release_lock(exc=None):
        if getattr(g, "_store_locked", False):
            g._store_locked = False
            try:
                LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return jsonify(envelope_error(err.error_id, err.message)), err.http_status

    @app.errorhandler(HTTPException)
    def _http_error(err):
        code = err.code or 500
        if code == 404:
            return jsonify(envelope_error(
                "ERR_INVALID_REQUEST", "No such resource path")), 404
        if code == 405:
            return jsonify(envelope_error(
                "ERR_INVALID_REQUEST", "Method not allowed for this path")), 405
        if code == 400:
            return jsonify(envelope_error(
                "ERR_INVALID_REQUEST", "Malformed request")), 400
        return jsonify(envelope_error("ERR_INVALID_REQUEST", str(err))), code

    @app.errorhandler(Exception)
    def _unhandled(err):
        return jsonify(envelope_error("ERR_INVALID_REQUEST", str(err))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
