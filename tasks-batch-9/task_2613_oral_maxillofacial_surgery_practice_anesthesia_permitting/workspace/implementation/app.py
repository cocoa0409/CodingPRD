"""Application entry point.

Boots a completely empty in-memory store on every process start: no seeding,
no fixtures, no persistence of any kind. The harness relaunches this process
via start.sh before each individual test, so a cold boot must always yield a
pristine world whose only non-default state is the logical clock default.
"""
import os
import traceback

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import db as store
from errors import ApiError
from response import error_response
from routes import (benefits, blocks, cases, directory, evaluations, events,
                    imaging, implants, ops, permits, practices)

BLUEPRINTS = (
    practices.bp,
    permits.bp,
    directory.bp,
    blocks.bp,
    cases.bp,
    evaluations.bp,
    benefits.bp,
    implants.bp,
    events.bp,
    imaging.bp,
    ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire():
        # Serialise request handling so that read-modify-write sequences over
        # the shared dict store stay atomic under the threaded dev server.
        store.db.lock.acquire()

    @app.teardown_request
    def _release(exc):
        try:
            store.db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.message)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response("ERR_RESOURCE_NOT_FOUND",
                              "The requested resource does not exist.")

    @app.errorhandler(405)
    def _not_allowed(err):
        return error_response("ERR_RESOURCE_NOT_FOUND",
                              "The requested resource does not exist.")

    @app.errorhandler(400)
    def _bad_request(err):
        return error_response("ERR_INVALID_REQUEST",
                              "The request body could not be parsed.")

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 401:
            return error_response("ERR_UNAUTHENTICATED", "Authentication is required.")
        if err.code == 403:
            return error_response("ERR_ROLE_NOT_PERMITTED", "The acting role may not call this endpoint.")
        if err.code and 400 <= err.code < 500:
            return error_response("ERR_INVALID_REQUEST", err.description or "Invalid request.")
        body = {
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": err.description or "Internal error."},
        }
        return jsonify(body), err.code or 500

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message)
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % err)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
