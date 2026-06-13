"""Patient Intake & Digital Forms API — Flask entry point.

Registers all route blueprints and the standard error handlers. Storage is
in-memory only (see db.py); the store starts empty on every boot, so a fresh
process wipes all state. Nothing is seeded at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_INVALID_REQUEST, HTTP_STATUS
from response import error_response

from routes.config import bp as config_bp
from routes.intake_sessions import bp as intake_sessions_bp
from routes.insurance import bp as insurance_bp
from routes.consent import bp as consent_bp
from routes.questionnaire import bp as questionnaire_bp
from routes.copay import bp as copay_bp
from routes.queue import bp as queue_bp
from routes.room_bookings import bp as room_bookings_bp
from routes.reminders import bp as reminders_bp
from routes.demographics import bp as demographics_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(intake_sessions_bp)
    app.register_blueprint(insurance_bp)
    app.register_blueprint(consent_bp)
    app.register_blueprint(questionnaire_bp)
    app.register_blueprint(copay_bp)
    app.register_blueprint(queue_bp)
    app.register_blueprint(room_bookings_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(demographics_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route — not an entity 404; report as a generic bad request
        # path. Entity-specific 404s are raised as ApiError above.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Malformed JSON body etc. -> ERR_INVALID_REQUEST.
        if e.code == 400:
            return error_response(ERR_INVALID_REQUEST,
                                  "Malformed request", HTTP_STATUS[ERR_INVALID_REQUEST])
        return error_response("ERR_HTTP_ERROR", e.description or "HTTP error",
                              e.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
