"""Resilient Flooring Plant Operations API — Flask entry point.

Storage is entirely in memory and completely empty on every boot: no seeds, no
fixtures, no persistence.  Every stamped instant reads the logical clock of
db.now(), never the wall clock.
"""

import os

from flask import Flask, g, jsonify

from db import begin_request, request_lock
from errors import ApiError
from middleware import authenticate
from response import error_response
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _before():
        request_lock.acquire()
        g.holds_lock = True
        begin_request()
        authenticate()
        return None

    @app.teardown_request
    def _teardown(_exception=None):
        if g.pop("holds_lock", False):
            try:
                request_lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        payload, status = error_response(err)
        return jsonify(payload), status

    @app.errorhandler(404)
    def _not_found(_err):
        payload, status = error_response(ApiError("ERR_INVALID_REQUEST"))
        return jsonify(payload), status

    @app.errorhandler(405)
    def _not_allowed(_err):
        payload, status = error_response(ApiError("ERR_INVALID_REQUEST"))
        return jsonify(payload), status

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            payload, status = error_response(err)
            return jsonify(payload), status
        payload, status = error_response(ApiError("ERR_INVALID_REQUEST"))
        return jsonify(payload), status

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
