"""Licensure Portability API — Flask application factory and entry point.

Storage is in-memory only (plain dicts in db.py); nothing is persisted, seeded
or preloaded, so a fresh process always starts with an empty store and the
logical clock at exactly 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

import db
import response
from errors import (
    ERR_INVALID_REQUEST, ERR_UNAUTHENTICATED, ApiError, HTTP_STATUS,
)
from routes import (
    applicants, applications, assignments, clock_control, credit_awards,
    disciplinary, evaluations, evaluators, licenses, permits, professions,
)

BLUEPRINTS = (
    professions.bp,
    applicants.bp,
    disciplinary.bp,
    applications.bp,
    evaluations.bp,
    credit_awards.bp,
    permits.bp,
    evaluators.bp,
    assignments.bp,
    licenses.bp,
    clock_control.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    # The store is a plain dict graph, so requests are serialised end to end.
    @app.before_request
    def _acquire_lock():
        db.LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            db.LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error_response(error.error_id, error.message,
                                       error.http_status)

    @app.errorhandler(404)
    def _not_found(error):
        return response.error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(error):
        return response.error_response(
            "ERR_METHOD_NOT_ALLOWED",
            "The method is not allowed for this resource.", 405)

    @app.errorhandler(400)
    def _bad_request(error):
        return response.error_response(
            ERR_INVALID_REQUEST, "The request could not be understood.",
            HTTP_STATUS[ERR_INVALID_REQUEST])

    @app.errorhandler(401)
    def _unauthenticated(error):
        return response.error_response(
            ERR_UNAUTHENTICATED, "Authentication headers are required.",
            HTTP_STATUS[ERR_UNAUTHENTICATED])

    @app.errorhandler(Exception)
    def _unhandled(error):
        if isinstance(error, ApiError):
            return _api_error(error)
        app.logger.exception("unhandled error")
        return response.error_response(
            "ERR_INTERNAL", "An unexpected internal error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
