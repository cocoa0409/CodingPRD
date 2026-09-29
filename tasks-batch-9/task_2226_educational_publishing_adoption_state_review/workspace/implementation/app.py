"""Adoption Review Press API - Flask application entrypoint.

Storage is entirely in-memory (plain Python dicts in ``db.py``); the process starts
with an empty store and a logical clock of 2026-08-01T00:00:00Z, and nothing is ever
seeded, preloaded or persisted to disk.
"""

import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from response import respond_error  # noqa: E402
from routes import clock as clock_routes  # noqa: E402
from routes import content_edits as content_edit_routes  # noqa: E402
from routes import cycles as cycle_routes  # noqa: E402
from routes import orders as order_routes  # noqa: E402
from routes import panels as panel_routes  # noqa: E402
from routes import pricing as pricing_routes  # noqa: E402
from routes import states as state_routes  # noqa: E402
from routes import submissions as submission_routes  # noqa: E402
from routes import titles as title_routes  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(state_routes.bp)
    app.register_blueprint(cycle_routes.bp)
    app.register_blueprint(title_routes.bp)
    app.register_blueprint(content_edit_routes.bp)
    app.register_blueprint(submission_routes.bp)
    app.register_blueprint(panel_routes.bp)
    app.register_blueprint(pricing_routes.bp)
    app.register_blueprint(order_routes.bp)
    app.register_blueprint(clock_routes.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return respond_error(error.error_id, error.message, error.http_status)

    @app.errorhandler(400)
    def handle_bad_request(_error):
        return respond_error(
            "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
        )

    @app.errorhandler(404)
    def handle_not_found(_error):
        return respond_error(
            "ERR_REFERENCED_RESOURCE_NOT_FOUND",
            "The requested path does not exist.",
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return respond_error(
            "ERR_INVALID_REQUEST",
            "The HTTP method is not allowed for this path.",
            405,
        )

    @app.errorhandler(415)
    def handle_unsupported_media(_error):
        return respond_error(
            "ERR_INVALID_REQUEST",
            "The request body must be JSON.",
            400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return respond_error(error.error_id, error.message, error.http_status)
        app.logger.exception("unhandled error: %s", error)
        return respond_error("ERR_INVALID_REQUEST", str(error), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
