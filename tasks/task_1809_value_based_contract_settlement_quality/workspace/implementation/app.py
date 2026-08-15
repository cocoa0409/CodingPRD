"""Value-Based Contract Settlement & Quality Withhold API — Flask entry point."""

from __future__ import annotations

import os
import threading

from flask import Flask, g

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.programs import bp as programs_bp
from routes.practice_groups import bp as practice_groups_bp
from routes.practices import bp as practices_bp
from routes.members import bp as members_bp
from routes.contracts import bp as contracts_bp
from routes.performance_years import bp as performance_years_bp
from routes.attribution import bp as attribution_bp
from routes.risk_scores import bp as risk_scores_bp
from routes.claims import bp as claims_bp
from routes.quality import bp as quality_bp
from routes.interim_reports import bp as interim_reports_bp
from routes.settlements import bp as settlements_bp
from routes.disputes import bp as disputes_bp
from routes.remittances import bp as remittances_bp
from routes.renewal_analyses import bp as renewal_analyses_bp

# The in-memory store is process-global; serialize requests so cascades are
# atomic (the harness may fire concurrent OCC probes).
_REQUEST_LOCK = threading.RLock()


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(practice_groups_bp)
    app.register_blueprint(practices_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(performance_years_bp)
    app.register_blueprint(attribution_bp)
    app.register_blueprint(risk_scores_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(quality_bp)
    app.register_blueprint(interim_reports_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(remittances_bp)
    app.register_blueprint(renewal_analyses_bp)

    @app.before_request
    def _acquire_lock():
        _REQUEST_LOCK.acquire()
        g._lock_held = True

    @app.teardown_request
    def _release_lock(exc=None):
        if getattr(g, "_lock_held", False):
            g._lock_held = False
            _REQUEST_LOCK.release()

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

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
