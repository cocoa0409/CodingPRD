"""Entry point: Flask app, error handlers, blueprint registration.

In-memory only; the store starts empty on every boot (no seeding).
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.employers import bp as employers_bp
from routes.protocols import bp as protocols_bp
from routes.workers import bp as workers_bp
from routes.encounters import bp as encounters_bp
from routes.clearances import bp as clearances_bp
from routes.drug_screens import bp as drug_screens_bp
from routes.custody_events import bp as custody_events_bp
from routes.injury_cases import bp as injury_cases_bp
from routes.work_statuses import bp as work_statuses_bp
from routes.surveillance_exams import bp as surveillance_exams_bp
from routes.invoices import bp as invoices_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        employers_bp,
        protocols_bp,
        workers_bp,
        encounters_bp,
        clearances_bp,
        drug_screens_bp,
        custody_events_bp,
        injury_cases_bp,
        work_statuses_bp,
        surveillance_exams_bp,
        invoices_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(exc):
        # Malformed JSON etc.
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc):
        return error_response("ERR_HTTP_ERROR", exc.description or "HTTP error",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
