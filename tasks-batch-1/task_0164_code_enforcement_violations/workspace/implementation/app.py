"""Code Enforcement & Violations API — Flask entry point.

In-memory only. The store starts EMPTY on every boot (no seeding). Each per-test
server restart wipes all state by virtue of being a fresh process.
"""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

# Route blueprints.
from routes.config import bp as config_bp
from routes.parties import bp as parties_bp
from routes.cases import bp as cases_bp
from routes.complaints import bp as complaints_bp
from routes.inspections import bp as inspections_bp
from routes.notices import bp as notices_bp
from routes.reinspections import bp as reinspections_bp
from routes.hearings import bp as hearings_bp
from routes.abatement import bp as abatement_bp
from routes.liens import bp as liens_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        config_bp,
        parties_bp,
        cases_bp,
        complaints_bp,
        inspections_bp,
        notices_bp,
        reinspections_bp,
        hearings_bp,
        abatement_bp,
        liens_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # An unmatched route path -> ERR_NOT_FOUND (PRD §2.8).
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", 400, "malformed request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_INVALID_REQUEST", e.code or 400, str(e))
        return error_response("ERR_INVALID_REQUEST", 500, "internal error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
