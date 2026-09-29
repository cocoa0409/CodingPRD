"""Placement Testing, Course Placement & Corequisite Remediation API.

In-memory only: every collection starts empty on each boot and no entity is
ever seeded, preloaded or hardcoded.
"""

import os

from flask import Flask

from errors import ApiError
from response import error
from routes import (
    administrations,
    appeals,
    attempts,
    clock,
    courses,
    determinations,
    overrides,
    registrations,
    requisites,
    rules,
    sections,
    students,
    studies,
)

BLUEPRINTS = (
    clock.bp,
    students.bp,
    courses.bp,
    requisites.bp,
    rules.bp,
    administrations.bp,
    attempts.bp,
    determinations.bp,
    appeals.bp,
    sections.bp,
    registrations.bp,
    overrides.bp,
    studies.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error("ERR_INVALID_REQUEST", "the requested path does not exist", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return error("ERR_INVALID_REQUEST", "the method is not allowed on this path", 405)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
