"""Talent Agency Booking API — Flask entry point.

In-memory store, empty on every boot. No entity data is seeded at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.agencies import bp as agencies_bp
from routes.casting_directors import bp as casting_directors_bp
from routes.talents import bp as talents_bp
from routes.comp_cards import bp as comp_cards_bp
from routes.casting_calls import bp as casting_calls_bp
from routes.submissions import bp as submissions_bp
from routes.audition_slots import bp as audition_slots_bp
from routes.availability_holds import bp as availability_holds_bp
from routes.deal_memos import bp as deal_memos_bp
from routes.bookings import bp as bookings_bp
from routes.commission_entries import bp as commission_entries_bp
from routes.payments import bp as payments_bp
from routes.residual_schedules import bp as residual_schedules_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        agencies_bp,
        casting_directors_bp,
        talents_bp,
        comp_cards_bp,
        casting_calls_bp,
        submissions_bp,
        audition_slots_bp,
        availability_holds_bp,
        deal_memos_bp,
        bookings_bp,
        commission_entries_bp,
        payments_bp,
        residual_schedules_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        # Malformed JSON etc. -> treat as invalid request shape.
        if err.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request.", 422)
        return error_response("ERR_INVALID_REQUEST", err.description or "Request error.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
