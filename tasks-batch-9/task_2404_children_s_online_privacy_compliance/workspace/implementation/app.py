"""Children's Online Privacy Compliance API.

Single-process Flask app over an in-memory store. Nothing is persisted and nothing
is seeded: every boot starts from an empty store and a logical clock pinned to
2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import (
    activities,
    age_screens,
    clock,
    compliance_runs,
    consents,
    evidence,
    integrations,
    notices,
    online_services,
    records,
    retention,
    rights,
    safe_harbor,
)

BLUEPRINTS = (
    online_services.bp,
    evidence.bp,
    age_screens.bp,
    notices.bp,
    activities.bp,
    consents.bp,
    records.bp,
    rights.bp,
    integrations.bp,
    retention.bp,
    compliance_runs.bp,
    safe_harbor.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        return error_body("ERR_NOT_FOUND", "The requested resource does not exist."), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return (
            error_body(
                "ERR_METHOD_NOT_ALLOWED",
                "That method is not allowed for this resource.",
            ),
            405,
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return (
                error_body("ERR_INVALID_REQUEST", "The request body could not be parsed."),
                422,
            )
        return error_body("ERR_INTERNAL", exc.description or "Request failed."), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", "An unexpected error occurred."), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
