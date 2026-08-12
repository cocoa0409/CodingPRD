"""Entry point: Flask app, error handlers, route registration."""

import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError, err_invalid_request, err_not_found  # noqa: E402
from response import error_response  # noqa: E402

from routes.records import bp as records_bp  # noqa: E402
from routes.research_cases import bp as research_cases_bp  # noqa: E402
from routes.events import bp as events_bp  # noqa: E402
from routes.committees import bp as committees_bp  # noqa: E402
from routes.ticket_tiers import bp as ticket_tiers_bp  # noqa: E402
from routes.registrations import bp as registrations_bp  # noqa: E402
from routes.groups import bp as groups_bp  # noqa: E402
from routes.programs import bp as programs_bp  # noqa: E402
from routes.preferences import bp as preferences_bp  # noqa: E402
from routes.campaigns import bp as campaigns_bp  # noqa: E402
from routes.pledges import bp as pledges_bp  # noqa: E402
from routes.publications import bp as publications_bp  # noqa: E402
from routes.clock import bp as clock_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(records_bp)
    app.register_blueprint(research_cases_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(committees_bp)
    app.register_blueprint(ticket_tiers_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(preferences_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(pledges_bp)
    app.register_blueprint(publications_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        err = err_not_found("Resource not found")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(405)
    def handle_405(_e):
        err = err_invalid_request("Method not allowed")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(400)
    def handle_400(_e):
        err = err_invalid_request("Malformed request")
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {exc}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
