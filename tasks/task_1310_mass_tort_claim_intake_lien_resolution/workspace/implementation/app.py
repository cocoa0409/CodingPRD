"""Mass Tort Claims API - main application entry point."""

import os
import re

from flask import Flask, request

from errors import ApiError, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_NOT_FOUND
from response import error_envelope


def create_app():
    app = Flask(__name__)

    # Register blueprints
    from routes.programs import bp as programs_bp
    from routes.tier_matrices import bp as tier_matrices_bp
    from routes.claimants import bp as claimants_bp
    from routes.claims import bp as claims_bp
    from routes.medical_records import bp as medical_records_bp
    from routes.liens import bp as liens_bp
    from routes.appeals import bp as appeals_bp
    from routes.tier_assignment import bp as tier_assignment_bp
    from routes.disbursements import bp as disbursements_bp
    from routes.closing import bp as closing_bp
    from routes.flat_aliases import bp as flat_bp

    app.register_blueprint(programs_bp)
    app.register_blueprint(tier_matrices_bp)
    app.register_blueprint(claimants_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(medical_records_bp)
    app.register_blueprint(liens_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(tier_assignment_bp)
    app.register_blueprint(disbursements_bp)
    app.register_blueprint(closing_bp)
    app.register_blueprint(flat_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_envelope(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_envelope(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_envelope(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(500)
    def handle_internal_error(e):
        return error_envelope("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)
