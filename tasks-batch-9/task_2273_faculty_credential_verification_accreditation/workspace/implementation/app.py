"""Faculty Credential Verification & Accreditation Compliance API.

Flask application factory plus the process entry point. All state lives in
process memory (see db.py) and starts empty on every boot.
"""

import os

from flask import Flask, g

import db
import middleware
import response
from errors import ApiError
from routes import (
    clock_routes, contracts, credentials, disciplines, faculty, justifications, pd,
    programs, reviews, rosters, sections, terms,
)

BLUEPRINTS = (
    clock_routes.bp,
    disciplines.bp,
    programs.bp,
    terms.bp,
    faculty.bp,
    credentials.bp,
    sections.bp,
    justifications.bp,
    rosters.bp,
    contracts.bp,
    pd.bp,
    reviews.bp,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _before():
        # One writer at a time: every request mutates the shared in-memory store.
        db.lock.acquire()
        g.holds_lock = True
        middleware.load_identity()

    @app.teardown_request
    def _teardown(exc=None):
        if g.pop("holds_lock", False):
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error("ERR_NOT_FOUND", "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return response.error("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this route.", 405)

    @app.errorhandler(Exception)
    def _internal(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        status = getattr(exc, "code", None)
        if status == 404:
            return response.error("ERR_NOT_FOUND",
                                  "The requested route does not exist.", 404)
        if status == 405:
            return response.error("ERR_METHOD_NOT_ALLOWED",
                                  "The method is not allowed for this route.", 405)
        if status == 400:
            return response.error("ERR_INVALID_REQUEST", "The request is malformed.", 400)
        app.logger.exception("unhandled error")
        return response.error("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
