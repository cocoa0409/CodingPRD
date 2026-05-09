"""Application entry point."""
import os
from flask import Flask

from errors import APIError
from response import error_response

from routes.productions import bp as productions_bp
from routes.scenes import bp as scenes_bp
from routes.actors import bp as actors_bp
from routes.roles import bp as roles_bp
from routes.locations import bp as locations_bp
from routes.budget import bp as budget_bp
from routes.equipment import bp as equipment_bp
from routes.vendor_invoices import bp as vendor_invoices_bp
from routes.crew import bp as crew_bp
from routes.audit_logs import bp as audit_logs_bp
from routes.test_endpoints import bp as test_endpoints_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Don't pretty-sort JSON keys (preserves field order, more deterministic)
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    # Register blueprints
    app.register_blueprint(productions_bp)
    app.register_blueprint(scenes_bp)
    app.register_blueprint(actors_bp)
    app.register_blueprint(roles_bp)
    app.register_blueprint(locations_bp)
    app.register_blueprint(budget_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(vendor_invoices_bp)
    app.register_blueprint(crew_bp)
    app.register_blueprint(audit_logs_bp)
    app.register_blueprint(test_endpoints_bp)

    # Error handlers
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Endpoint not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_VALIDATION", 422, "Bad request")

    @app.errorhandler(415)
    def handle_415(err):
        return error_response("ERR_VALIDATION", 422, "Unsupported media type")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface unexpected errors as ERR_VALIDATION 500-ish — but PRD doesn't
        # specify 5xx. Fall back to validation error to keep clients happy.
        # Log to stderr for debugging.
        import traceback, sys
        traceback.print_exc(file=sys.stderr)
        return error_response("ERR_VALIDATION", 500, f"Internal error: {err.__class__.__name__}")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
