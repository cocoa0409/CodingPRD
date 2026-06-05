"""Trademark Filing & Prosecution API — Flask entry point.

Storage is in-memory only (Python dicts in db.py); nothing is seeded at startup.
The server boots clean on every process launch (per-test-server isolation).
"""

import os
import sys
from flask import Flask

from errors import APIError
from response import error as error_response

# Route blueprints
from routes.applicants import bp as applicants_bp
from routes.attorneys import bp as attorneys_bp
from routes.nice_classes import bp as nice_classes_bp
from routes.applications import bp as applications_bp
from routes.office_actions import bp as office_actions_bp, resp_bp as oa_responses_bp
from routes.statements_of_use import bp as statements_of_use_bp
from routes.ttab import bp as ttab_bp
from routes.registrations import bp as registrations_bp, mf_bp as maintenance_filings_bp
from routes.madrid import bp as madrid_bp
from routes.system import bp as system_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Preserve insertion order in JSON responses.
    app.json.sort_keys = False

    app.register_blueprint(applicants_bp)
    app.register_blueprint(attorneys_bp)
    app.register_blueprint(nice_classes_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(office_actions_bp)
    app.register_blueprint(oa_responses_bp)
    app.register_blueprint(statements_of_use_bp)
    app.register_blueprint(ttab_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(maintenance_filings_bp)
    app.register_blueprint(madrid_bp)
    app.register_blueprint(system_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_VALIDATION", 400, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.http_status, e.message)
        print(f"[unhandled] {type(e).__name__}: {e}", file=sys.stderr)
        return error_response(
            "ERR_VALIDATION", 400, f"Unexpected error: {type(e).__name__}"
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
