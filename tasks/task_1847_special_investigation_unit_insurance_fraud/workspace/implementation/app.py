"""SIU Fraud API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.adjusters import bp as adjusters_bp
from routes.assignments import bp as assignments_bp
from routes.bureau import bp as bureau_bp
from routes.cases import bp as cases_bp
from routes.claims import bp as claims_bp
from routes.clock import bp as clock_bp
from routes.euo import bp as euo_bp
from routes.evidence import bp as evidence_bp
from routes.investigators import bp as investigators_bp
from routes.patterns import bp as patterns_bp
from routes.referrals import bp as referrals_bp
from routes.reports import bp as reports_bp
from routes.restitution import bp as restitution_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(adjusters_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(bureau_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(clock_bp)
    app.register_blueprint(euo_bp)
    app.register_blueprint(evidence_bp)
    app.register_blueprint(investigators_bp)
    app.register_blueprint(patterns_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(restitution_bp)

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
