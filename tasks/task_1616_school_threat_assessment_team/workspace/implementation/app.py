"""School Threat Assessment API — Flask entry point."""

from __future__ import annotations

import os
import threading

from flask import Flask, g

from errors import ApiError
from response import error_response

from routes.admin import bp as admin_bp
from routes.cases import bp as cases_bp
from routes.interviews import bp as interviews_bp
from routes.assessments import bp as assessments_bp
from routes.plans import bp as plans_bp
from routes.referrals import bp as referrals_bp
from routes.checkins import bp as checkins_bp
from routes.reentry import bp as reentry_bp


# A single process-wide lock serializes request handling. The store is
# in-memory and the OCC check on plan activation must be atomic with the
# mutation, so concurrent requests (waitress threads) are funneled through
# one lock. Requests are fast; serialization is not a throughput concern.
_REQUEST_LOCK = threading.RLock()


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(admin_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(interviews_bp)
    app.register_blueprint(assessments_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(checkins_bp)
    app.register_blueprint(reentry_bp)

    @app.before_request
    def _acquire_request_lock():
        _REQUEST_LOCK.acquire()
        g._request_lock_held = True

    @app.teardown_request
    def _release_request_lock(exc=None):
        if getattr(g, "_request_lock_held", False):
            g._request_lock_held = False
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
