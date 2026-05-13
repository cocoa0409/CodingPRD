"""Crowdsource Design API — Flask application entry point."""
import os

from flask import Flask

from errors import APIError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.parties import bp as parties_bp
from routes.projects import bp as projects_bp
from routes.submissions import bp as submissions_bp
from routes.review_stages import bp as review_stages_bp
from routes.review_assignments import bp as review_assignments_bp
from routes.copyright_transfers import bp as copyright_bp
from routes.prize_payments import bp as prize_payments_bp
from routes.disputes import bp as disputes_bp
from routes.audit_events import bp as audit_bp
from routes.system import bp as system_bp


def create_app():
    app = Flask(__name__)

    # Per PRD: response envelope is uniform; no global prefix.
    for bp in (
        catalog_bp,
        parties_bp,
        projects_bp,
        submissions_bp,
        review_stages_bp,
        review_assignments_bp,
        copyright_bp,
        prize_payments_bp,
        disputes_bp,
        audit_bp,
        system_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method Not Allowed", 404)

    @app.errorhandler(500)
    def handle_500(e):
        return error_response("ERR_VALIDATION", f"Internal error: {e}", 500)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    create_app().run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
