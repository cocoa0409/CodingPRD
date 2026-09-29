"""Public Art Conservation API -- Flask application factory and entry point.

Storage is entirely in-memory and starts empty on every boot: the process holds
nothing but Python dicts, and no entity is ever seeded, preloaded or hardcoded.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_money
import routes_ops
import routes_registry
import routes_rights
import routes_survey
import routes_treatment
from db import db
from errors import HTTP_STATUS, ApiError
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_survey.bp)
    app.register_blueprint(routes_treatment.bp)
    app.register_blueprint(routes_rights.bp)
    app.register_blueprint(routes_money.bp)
    app.register_blueprint(routes_ops.bp)

    # One request at a time: every cascade must be observed whole, never halfway.
    @app.before_request
    def _acquire():
        db.lock.acquire()

    @app.teardown_request
    def _release(exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def _not_found(err):
        return (
            jsonify(error_body("ERR_NOT_FOUND", "No such resource or route.")),
            HTTP_STATUS["ERR_NOT_FOUND"],
        )

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return (
            jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed on this route.")),
            HTTP_STATUS["ERR_METHOD_NOT_ALLOWED"],
        )

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 400:
            return (
                jsonify(error_body("ERR_INVALID_REQUEST", err.description or "Bad request.")),
                400,
            )
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", err.description or "Request failed.")),
            err.code or 400,
        )

    @app.errorhandler(Exception)
    def _unexpected(err):
        if isinstance(err, (ApiError, HTTPException)):
            raise err
        return (
            jsonify(error_body("ERR_INTERNAL", "Unexpected server error: %s" % err)),
            HTTP_STATUS["ERR_INTERNAL"],
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
