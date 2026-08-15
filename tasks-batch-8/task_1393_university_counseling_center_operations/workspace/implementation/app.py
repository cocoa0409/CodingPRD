"""University Counseling Center API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.students import bp as students_bp
from routes.counselors import bp as counselors_bp
from routes.intakes import bp as intakes_bp
from routes.episodes import bp as episodes_bp
from routes.sessions import bp as sessions_bp
from routes.notes import bp as notes_bp
from routes.groups import bp as groups_bp
from routes.crisis import bp as crisis_bp
from routes.referrals import bp as referrals_bp
from routes.policies import bp as policies_bp
from routes.outcomes import bp as outcomes_bp
from routes.reports import bp as reports_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(students_bp)
    app.register_blueprint(counselors_bp)
    app.register_blueprint(intakes_bp)
    app.register_blueprint(episodes_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(crisis_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(outcomes_bp)
    app.register_blueprint(reports_bp)

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
