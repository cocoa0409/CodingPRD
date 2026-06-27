"""Yearbook Production & Sales API — Flask entry point.

Boots cleanly from a fresh process on every invocation. The in-memory store
starts EMPTY (no seeding). Listens on $PORT (default 10000), binds 0.0.0.0.
"""
import os

from flask import Flask, request

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.yearbooks import bp as yearbooks_bp
from routes.pages import bp as pages_bp
from routes.submissions import bp as submissions_bp
from routes.staff_assignments import bp as staff_assignments_bp
from routes.ad_contracts import bp as ad_contracts_bp
from routes.proofs import bp as proofs_bp
from routes.presale_orders import bp as presale_orders_bp
from routes.print_runs import bp as print_runs_bp
from routes.distribution_records import bp as distribution_records_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register blueprints. Order matters only for overlapping static vs dynamic
    # segments; Flask handles that, but more-specific collection routes
    # (e.g. /yearbooks/pages) are registered alongside /yearbooks/<id> safely
    # because Flask prefers static rule segments over variable ones.
    app.register_blueprint(pages_bp)
    app.register_blueprint(submissions_bp)
    app.register_blueprint(staff_assignments_bp)
    app.register_blueprint(ad_contracts_bp)
    app.register_blueprint(proofs_bp)
    app.register_blueprint(presale_orders_bp)
    app.register_blueprint(print_runs_bp)
    app.register_blueprint(distribution_records_bp)
    app.register_blueprint(yearbooks_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route -> standard not-found envelope
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_INVALID_REQUEST, "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        # Surface unexpected failures in the standard envelope (500).
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
