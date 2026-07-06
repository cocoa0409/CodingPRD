"""Survey & Market-Research Panel API — entry point.

Registers all route blueprints and the global error handlers. Storage is
in-memory (see db.py); the store starts EMPTY on every boot — nothing is
seeded. Run via start.sh, which honors $PORT, binds 0.0.0.0, and runs this in
the foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from routes.deliveries import bp as deliveries_bp
from routes.focus_groups import bp as focus_groups_bp
from routes.panelists import bp as panelists_bp
from routes.participations import bp as participations_bp
from routes.payouts import bp as payouts_bp
from routes.studies import bp as studies_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(studies_bp)
    app.register_blueprint(panelists_bp)
    app.register_blueprint(participations_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(focus_groups_bp)
    app.register_blueprint(deliveries_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / unresolved path id -> ERR_NOT_FOUND (PRD §2.5).
        return response.error_response(
            errors.ERR_NOT_FOUND[0], "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error_response(
            errors.ERR_NOT_FOUND[0], "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return response.error_response(
            errors.ERR_VALIDATION[0], "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Let Werkzeug HTTP exceptions (already handled above) pass through.
        if isinstance(exc, HTTPException):
            return response.error_response(
                errors.ERR_VALIDATION[0], str(exc), exc.code or 400)
        # Defensive: never leak a stack trace as a 500 HTML page.
        return response.error_response(
            errors.ERR_VALIDATION[0], "Internal error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
