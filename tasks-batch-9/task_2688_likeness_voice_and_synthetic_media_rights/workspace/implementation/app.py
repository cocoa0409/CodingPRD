"""Likeness, Voice and Synthetic Media Rights Clearance API.

Entry point: wires the blueprints, installs the error envelope handlers and
serialises every request behind one lock so cascades stay atomic.  The store is
purely in-memory and starts completely empty on every boot -- nothing is seeded,
preloaded or hardcoded here or in any imported module.
"""

import os

from flask import Flask, g

import core
from core import ApiError, LOCK, error_body
import routes_asset
import routes_case
import routes_consent
import routes_license
import routes_perf
import routes_reference
import routes_talent


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_reference.bp)
    app.register_blueprint(routes_talent.bp)
    app.register_blueprint(routes_consent.bp)
    app.register_blueprint(routes_asset.bp)
    app.register_blueprint(routes_perf.bp)
    app.register_blueprint(routes_license.bp)
    app.register_blueprint(routes_case.bp)

    @app.before_request
    def _serialise():
        LOCK.acquire()
        g._locked = True
        g._touched = set()

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(404)
    def _not_found(exc):
        return error_body("ERR_INVALID_REQUEST", "no such route"), 404

    @app.errorhandler(405)
    def _bad_method(exc):
        return error_body("ERR_INVALID_REQUEST",
                          "that method is not allowed on this route"), 405

    @app.errorhandler(400)
    def _bad_request(exc):
        return error_body("ERR_INVALID_REQUEST", "the request could not be parsed"), 400

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_body(exc.error_id, exc.message), exc.http_status
        status = getattr(exc, "code", None)
        if isinstance(status, int) and 400 <= status < 600:
            return error_body("ERR_INVALID_REQUEST", str(exc)), status
        app.logger.exception("unhandled error")
        return error_body("ERR_INVALID_REQUEST", "internal error: %s" % exc), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
