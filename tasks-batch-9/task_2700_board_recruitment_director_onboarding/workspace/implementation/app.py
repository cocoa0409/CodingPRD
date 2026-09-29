"""Board recruitment and director onboarding API.

Every blueprint mounts under /governance.  Storage is process-local and
in-memory (see store.py): a fresh process starts with all seventeen
collections empty, and nothing is ever seeded, cached or written to disk.
"""

import os

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes import (
    candidate_routes,
    committee_routes,
    comp_routes,
    director_routes,
    directorship_routes,
    interview_routes,
    onboarding_routes,
    policy_routes,
    screen_routes,
    slate_routes,
)

PREFIX = "/governance"

BLUEPRINTS = (
    policy_routes.bp,
    director_routes.bp,
    candidate_routes.bp,
    screen_routes.bp,
    directorship_routes.bp,
    interview_routes.bp,
    committee_routes.bp,
    slate_routes.bp,
    onboarding_routes.bp,
    comp_routes.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(404)
    def _no_route(exc):
        return error_response("ERR_NOT_FOUND", "No such resource or route.", 404)

    @app.errorhandler(405)
    def _no_method(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "That method is not allowed on this route.", 405)

    @app.errorhandler(415)
    def _no_media(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "Request body must be JSON.", 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
