"""Flask application entry point."""

from __future__ import annotations

import os

from flask import Flask

import db  # noqa: F401  (initializes the in-memory store module)
import errors
from errors import ApiError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.clock import bp as clock_bp
    from routes.programs import bp as programs_bp
    from routes.contractors import bp as contractors_bp
    from routes.certifications import bp as certifications_bp
    from routes.customers import bp as customers_bp
    from routes.leads import bp as leads_bp
    from routes.projects import bp as projects_bp
    from routes.work_orders import bp as work_orders_bp
    from routes.inspectors import bp as inspectors_bp
    from routes.inspections import bp as inspections_bp
    from routes.payments import bp as payments_bp
    from routes.complaints import bp as complaints_bp
    from routes.reports import bp as reports_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(contractors_bp)
    app.register_blueprint(certifications_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(leads_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(inspectors_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(complaints_bp)
    app.register_blueprint(reports_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response(errors.ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(_):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_generic(err):
        # Surface unexpected errors as a generic 400 to keep the envelope intact.
        return error_response(errors.ERR_INVALID_INSPECTION_PAYLOAD, str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
