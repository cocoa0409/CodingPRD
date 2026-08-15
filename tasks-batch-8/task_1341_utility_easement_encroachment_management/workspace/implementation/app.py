"""Utility Easement Encroachment API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response
from services import domain

from routes.cases import bp as cases_bp
from routes.documents import bp as documents_bp
from routes.encroachments import bp as encroachments_bp
from routes.offers import bp as offers_bp
from routes.permits import bp as permits_bp
from routes.vegetation import bp as vegetation_bp
from routes.title_searches import bp as title_searches_bp
from routes.referrals import bp as referrals_bp
from routes.flat import bp as flat_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(cases_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(encroachments_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(vegetation_bp)
    app.register_blueprint(title_searches_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(flat_bp)
    app.register_blueprint(clock_bp)

    @app.before_request
    def _lazy_deadline_sweep():
        # Deadline-based auto-transitions are evaluated lazily on every request
        # (and eagerly again when the clock endpoint advances time).
        from flask import request

        if request.path == "/_clock/set_current_utc":
            return None
        domain.sweep_deadlines()
        return None

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
