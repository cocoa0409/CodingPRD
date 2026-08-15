"""Cleanroom Assembly & Environmental Monitoring API — Flask entry point."""

import os

from flask import Flask

from db import GLOBAL_LOCK
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.clock import bp as clock_bp
    from routes.rooms import bp as rooms_bp
    from routes.samples import bp as samples_bp
    from routes.certifications import bp as certifications_bp
    from routes.people import bp as people_bp
    from routes.transfers import bp as transfers_bp
    from routes.batches import bp as batches_bp
    from routes.cleaning import bp as cleaning_bp
    from routes.audits import bp as audits_bp

    for blueprint in (
        clock_bp,
        rooms_bp,
        samples_bp,
        certifications_bp,
        people_bp,
        transfers_bp,
        batches_bp,
        cleaning_bp,
        audits_bp,
    ):
        app.register_blueprint(blueprint)

    # Every request runs under one global reentrant lock so multi-step side
    # effects (cascades, posture recompute) are atomic per request.
    @app.before_request
    def _acquire_store_lock():
        GLOBAL_LOCK.acquire()

    @app.teardown_request
    def _release_store_lock(exc):
        try:
            GLOBAL_LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_not_found(err):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(err):
        return error_response(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def _handle_bad_request(err):
        return error_response(ERR_INVALID_REQUEST, "malformed request", 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_response(ERR_INVALID_REQUEST,
                              "unexpected server error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
