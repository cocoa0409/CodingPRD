"""HEDIS Quality Measures API — entry point.

In-memory only; the store starts EMPTY on every boot (no seeding).
Logical clock starts at 2026-05-01T00:00:00Z (§2.5).
"""
import os

from flask import Flask

import errors
from errors import ApiError
from response import error_response
from routes.seasons import bp as seasons_bp
from routes.members import bp as members_bp
from routes.runs import bp as runs_bp
from routes.abstractions import bp as abstractions_bp
from routes.supplemental import bp as supplemental_bp
from routes.gaps_audit import bp as gaps_audit_bp


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(seasons_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(abstractions_bp)
    app.register_blueprint(supplemental_bp)
    app.register_blueprint(gaps_audit_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(_):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # never leak a stack trace through the envelope
        return error_response(errors.ERR_INVALID_REQUEST, 400, str(exc))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
