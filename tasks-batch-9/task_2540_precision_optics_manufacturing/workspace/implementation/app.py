"""Precision Optics Manufacturing Execution API — Flask application factory.

All state is held in process memory (see store.py). Nothing is seeded: every
entity in the system is created through the declared endpoints.
"""

import os
import threading

from flask import Flask, g, jsonify, request

import routes_assemblies
import routes_clock
import routes_coating
import routes_designs
import routes_docs
import routes_export
import routes_glass
import routes_inspection
import routes_metrology
import routes_workorders
from common import error_body
from errors import ApiError
from store import store

BLUEPRINTS = [
    routes_designs.bp,
    routes_glass.bp,
    routes_workorders.bp,
    routes_metrology.bp,
    routes_coating.bp,
    routes_assemblies.bp,
    routes_inspection.bp,
    routes_export.bp,
    routes_docs.bp,
    routes_clock.bp,
]

# Every request is serialised: cascades must be observed atomically.
_request_lock = threading.Lock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.before_request
    def _before():
        _request_lock.acquire()
        g._holds_request_lock = True
        store.begin_request()
        return None

    @app.teardown_request
    def _teardown(_exc):
        if g.pop("_holds_request_lock", False):
            _request_lock.release()

    @app.errorhandler(ApiError)
    def _api_error(err):
        body, status = error_body(err)
        return jsonify(body), status

    @app.errorhandler(404)
    def _not_found(_err):
        body, status = error_body(ApiError(
            "ERR_INVALID_REQUEST",
            "No route matches %s %s." % (request.method, request.path)))
        return jsonify(body), status

    @app.errorhandler(405)
    def _not_allowed(_err):
        body, status = error_body(ApiError(
            "ERR_INVALID_REQUEST",
            "Method %s is not allowed for %s." % (request.method, request.path)))
        return jsonify(body), status

    @app.errorhandler(Exception)
    def _unexpected(err):
        if isinstance(err, ApiError):
            body, status = error_body(err)
            return jsonify(body), status
        body, _status = error_body(ApiError("ERR_INVALID_REQUEST", str(err)))
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
