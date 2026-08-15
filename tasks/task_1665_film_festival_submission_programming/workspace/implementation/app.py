"""Film Festival Submission & Programming API — entry point.

Python + Flask, in-memory storage only. Boots cleanly from a fresh process:
the store starts empty and the logical clock reads exactly
2026-08-01T00:00:00Z until a test drives it forward.
"""

import os

from flask import Flask

from errors import ApiError
from util import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_editions
    import routes_submissions
    import routes_screening
    import routes_slates
    import routes_scheduling
    import routes_travel
    import routes_agreements
    import routes_awards

    for module in (routes_editions, routes_submissions, routes_screening,
                   routes_slates, routes_scheduling, routes_travel,
                   routes_agreements, routes_awards):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(
            ApiError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(
            ApiError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(
            ApiError("ERR_VALIDATION", "Request validation failed", 400))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(
            ApiError("ERR_VALIDATION", "Unexpected server error: %s" % err,
                     500))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
