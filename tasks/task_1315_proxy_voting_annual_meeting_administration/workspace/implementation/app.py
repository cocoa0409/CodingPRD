"""Proxy Voting & Annual Meeting Administration API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.meetings import bp as meetings_bp
from routes.accounts import bp as accounts_bp
from routes.broker_searches import bp as broker_searches_bp
from routes.distributions import bp as distributions_bp
from routes.proposals import bp as proposals_bp
from routes.votes import bp as votes_bp
from routes.sessions import bp as sessions_bp
from routes.questions import bp as questions_bp
from routes.challenges import bp as challenges_bp
from routes.campaigns import bp as campaigns_bp
from routes.certifications import bp as certifications_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(meetings_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(broker_searches_bp)
    app.register_blueprint(distributions_bp)
    app.register_blueprint(proposals_bp)
    app.register_blueprint(votes_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(questions_bp)
    app.register_blueprint(challenges_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(certifications_bp)
    app.register_blueprint(clock_bp)

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
    import errno
    import time

    port = int(os.environ.get("PORT", "10000"))

    def _serve_with_bind_retry() -> None:
        """Bind, tolerating the predecessor's socket teardown.

        Under per-test-server isolation the harness SIGKILLs the previous
        server on this port and respawns immediately; on a loaded host the
        killed process's LISTEN socket can outlive the kill by a few hundred
        ms, so the first bind attempt can transiently fail with EADDRINUSE.
        Retry for up to ~10s (well inside the harness's restart-poll window).
        """
        delay = 0.2
        deadline = time.monotonic() + 10.0
        while True:
            try:
                from waitress import serve

                serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
                return
            except ImportError:
                app.run(host="0.0.0.0", port=port, threaded=True)
                return
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE or time.monotonic() >= deadline:
                    raise
                time.sleep(delay)
                delay = min(delay * 1.5, 1.0)

    _serve_with_bind_retry()
