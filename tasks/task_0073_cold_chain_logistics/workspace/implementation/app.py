"""Cold Chain Logistics API — entry point."""

import os

from flask import Flask

from errors import APIError
from response import error_response

from routes.clock_routes import bp as clock_bp
from routes.vehicles import bp as vehicles_bp
from routes.drivers import bp as drivers_bp
from routes.transport_tasks import bp as tasks_bp
from routes.temperature_readings import bp as readings_bp
from routes.alerts import bp as alerts_bp
from routes.damage_assessments import bp as assessments_bp
from routes.responsibility_decisions import bp as decisions_bp
from routes.insurance_claims import bp as claims_bp
from routes.compliance_reports import bp as reports_bp
from routes.audit_log import bp as audit_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_NOT_FOUND", 404, "Route not found.")

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_FORBIDDEN", 403, "Method not allowed for this route.")

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_VALIDATION", 422, "Malformed request.")

    @app.errorhandler(500)
    def handle_500(_e):
        return error_response("ERR_VALIDATION", 422, "Internal error.")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Catch-all so the response envelope is preserved
        if isinstance(e, APIError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_VALIDATION", 422, f"Unexpected error: {e}")

    # Register blueprints
    for bp in (
        clock_bp,
        vehicles_bp,
        drivers_bp,
        tasks_bp,
        readings_bp,
        alerts_bp,
        assessments_bp,
        decisions_bp,
        claims_bp,
        reports_bp,
        audit_bp,
    ):
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
