"""Minor League Affiliation & Player Development Pipeline API.

Entry point: registers every route blueprint, wraps each request in the
snapshot/version machinery of Section 2.4, and renders every failure through
the Section 2.2 error envelope.  The store starts completely empty: nothing is
seeded, preloaded or hardcoded at boot.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import store
from errors import ApiError
from routes import (affiliates, agreements, assignments, clock, players, plans,
                    reports, reviews, signings, staff)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (affiliates, agreements, reviews, staff, players, assignments,
                   plans, reports, signings, clock):
        app.register_blueprint(module.bp)

    @app.before_request
    def _begin():
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        store.rollback_request()
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        store.rollback_request()
        if exc.code == 404:
            return envelope.error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return envelope.error_response("ERR_METHOD_NOT_ALLOWED",
                                           "Method not allowed.", 405)
        if exc.code == 400:
            return envelope.error_response("ERR_INVALID_REQUEST",
                                           "The request body is not well-shaped.", 400)
        return envelope.error_response("ERR_INTERNAL",
                                       exc.description or "Internal server error.",
                                       exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        store.rollback_request()
        return envelope.error_response("ERR_INTERNAL", str(exc) or "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
