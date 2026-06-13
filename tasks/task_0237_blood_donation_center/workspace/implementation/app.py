"""Blood Donation Center API — Flask entry point.

In-memory only: the store starts empty on every boot, no seeding. Reads $PORT
(default 10000), binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask

import errors
from errors import ApiError
from response import error as error_response
from routes.adverse_reactions import bp as adverse_reactions_bp
from routes.appointments import bp as appointments_bp
from routes.blood_units import bp as blood_units_bp
from routes.centers import bp as centers_bp
from routes.deferrals import bp as deferrals_bp
from routes.donations import bp as donations_bp
from routes.donors import bp as donors_bp
from routes.inventory_buckets import bp as inventory_buckets_bp
from routes.recall_events import bp as recall_events_bp
from routes.screenings import bp as screenings_bp
from routes.slots import bp as slots_bp
from routes.test_results import bp as test_results_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        centers_bp,
        donors_bp,
        deferrals_bp,
        slots_bp,
        appointments_bp,
        screenings_bp,
        donations_bp,
        test_results_bp,
        blood_units_bp,
        adverse_reactions_bp,
        recall_events_bp,
        inventory_buckets_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route -> generic not-found in the standard envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(errors.ERR_INVALID_REQUEST, "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response(errors.ERR_INVALID_REQUEST, "Unexpected server error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
