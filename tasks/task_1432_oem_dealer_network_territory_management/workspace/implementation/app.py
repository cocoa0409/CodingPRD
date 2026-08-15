"""OEM Dealer Network & Territory Management API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.dealers import bp as dealers_bp
from routes.agreements import bp as agreements_bp
from routes.assignments import bp as assignments_bp
from routes.targets import bp as targets_bp
from routes.sales import bp as sales_bp
from routes.advances import bp as advances_bp
from routes.claims import bp as claims_bp
from routes.returns import bp as returns_bp
from routes.certifications import bp as certifications_bp
from routes.leads import bp as leads_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        dealers_bp,
        agreements_bp,
        assignments_bp,
        targets_bp,
        sales_bp,
        advances_bp,
        claims_bp,
        returns_bp,
        certifications_bp,
        leads_bp,
    ):
        app.register_blueprint(bp, url_prefix="/network")

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Surface unexpected errors in the standard envelope.
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
