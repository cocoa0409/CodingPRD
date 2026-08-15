"""Campus Recruiting API — Flask entry point."""

import os
from flask import Flask

from errors import ApiError, err_not_found, err_validation
from response import error_response

API_PREFIX = "/campus-recruiting"


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Import and register blueprints under the API prefix
    from routes.seasons import bp as seasons_bp
    from routes.school_targets import bp as school_targets_bp
    from routes.campus_events import bp as campus_events_bp
    from routes.candidates import bp as candidates_bp
    from routes.applications import bp as applications_bp
    from routes.employees import bp as employees_bp
    from routes.interview_days import bp as interview_days_bp
    from routes.interview_slots import bp as interview_slots_bp
    from routes.evaluations import bp as evaluations_bp
    from routes.offers import bp as offers_bp
    from routes.stipend_disbursements import bp as stipend_bp
    from routes.intern_projects import bp as projects_bp
    from routes.project_assignments import bp as assignments_bp
    from routes.intern_evaluations import bp as intern_evals_bp

    for b in (
        seasons_bp,
        school_targets_bp,
        campus_events_bp,
        candidates_bp,
        applications_bp,
        employees_bp,
        interview_days_bp,
        interview_slots_bp,
        evaluations_bp,
        offers_bp,
        stipend_bp,
        projects_bp,
        assignments_bp,
        intern_evals_bp,
    ):
        app.register_blueprint(b, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(e: ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        err = err_not_found("Route not found")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(405)
    def handle_405(e):
        err = err_not_found("Method not allowed")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(Exception)
    def handle_exception(e: Exception):
        # Catch-all -> 400 validation-style error is safer than 500
        err = err_validation(f"Unhandled error: {e}")
        return error_response(err.error_id, err.message, err.http_status)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
