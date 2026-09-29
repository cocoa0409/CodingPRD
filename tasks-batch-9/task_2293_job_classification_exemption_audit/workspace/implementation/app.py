"""Job Classification & Exemption Audit API.

Boots empty on every process start: all state lives in the in-memory dicts of
db.py and nothing is seeded, preloaded or persisted.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    audit_projects,
    back_wage_estimates,
    clock,
    contractor_reviews,
    duty_statements,
    exemption_analyses,
    interviews,
    job_change_triggers,
    job_families,
    positions,
    reclassification_cases,
    state_rules,
    voluntary_corrections,
)

BLUEPRINTS = (
    clock.bp,
    state_rules.bp,
    audit_projects.bp,
    job_families.bp,
    positions.bp,
    duty_statements.bp,
    interviews.bp,
    exemption_analyses.bp,
    reclassification_cases.bp,
    back_wage_estimates.bp,
    voluntary_corrections.bp,
    contractor_reviews.bp,
    job_change_triggers.bp,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "The requested route does not exist.", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Bad request.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
