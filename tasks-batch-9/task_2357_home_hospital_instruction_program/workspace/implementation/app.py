"""Home and Hospital Instruction API — application factory and entry point.

Storage is entirely in memory (see `db.py`); the process starts with an empty
store on every boot and nothing is ever seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    assignments,
    attendance_entries,
    cases,
    certifications,
    clock as clock_routes,
    entitlement_rules,
    extension_requests,
    pacing_syncs,
    safety_reviews,
    sessions,
    sped_service_logs,
    students,
    teachers,
    transition_plans,
)

BLUEPRINTS = (
    clock_routes.bp,
    students.bp,
    teachers.bp,
    entitlement_rules.bp,
    cases.bp,
    certifications.bp,
    assignments.bp,
    safety_reviews.bp,
    sessions.bp,
    attendance_entries.bp,
    extension_requests.bp,
    transition_plans.bp,
    pacing_syncs.bp,
    sped_service_logs.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.failure(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            return response.failure("ERR_NOT_FOUND", "Unknown route.", 404)
        if error.code == 405:
            return response.failure(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this route.", 405
            )
        if error.code == 400:
            return response.failure("ERR_VALIDATION", "The request is malformed.", 400)
        return response.failure(
            "ERR_INTERNAL", error.description or "Request failed.", error.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return response.failure("ERR_INTERNAL", str(error), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False)
