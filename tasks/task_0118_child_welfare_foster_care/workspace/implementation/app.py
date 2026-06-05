"""Child Welfare & Foster Care API — Flask entry point.

Boots a fresh, EMPTY in-memory store on every process start (no seeding). Reads
$PORT (default 10000), binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask

import response
from errors import ApiError

from routes.clock_routes import bp as clock_bp
from routes.caseworkers import bp as caseworkers_bp
from routes.referrals import bp as referrals_bp
from routes.investigations import bp as investigations_bp
from routes.cases import bp as cases_bp
from routes.children import bp as children_bp
from routes.foster_homes import bp as foster_homes_bp
from routes.caregiver_screenings import bp as screenings_bp
from routes.placements import bp as placements_bp
from routes.case_plans import bp as case_plans_bp
from routes.visitations import bp as visitations_bp
from routes.hearings import bp as hearings_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(caseworkers_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(investigations_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(children_bp)
    app.register_blueprint(foster_homes_bp)
    app.register_blueprint(screenings_bp)
    app.register_blueprint(placements_bp)
    app.register_blueprint(case_plans_bp)
    app.register_blueprint(visitations_bp)
    app.register_blueprint(hearings_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return response.error("ERR_INVALID_REQUEST", "Malformed request.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return response.error(err.error_id, err.message, err.http_status)
        return response.error("ERR_INVALID_REQUEST", f"Unexpected error: {err}", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
