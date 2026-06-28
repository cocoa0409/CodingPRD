"""Paint & Sip Event Studio API — entry point and error handlers.

In-memory only. Every boot starts with empty state (no seeding).
Binds 0.0.0.0:$PORT (default 10000), foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.studios import bp as studios_bp
from routes.artists import bp as artists_bp
from routes.customers import bp as customers_bp
from routes.gift_cards import bp as gift_cards_bp
from routes.events import bp as events_bp
from routes.assignments import bp as assignments_bp
from routes.kit_batches import bp as kit_batches_bp
from routes.reservations import bp as reservations_bp
from routes.attendees import bp as attendees_bp
from routes.payments import bp as payments_bp
from routes.walk_ins import bp as walk_ins_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(studios_bp)
    app.register_blueprint(artists_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(gift_cards_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(kit_batches_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(attendees_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(walk_ins_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exc(e):
        # Malformed JSON / bad requests surface as 400 ERR_VALIDATION.
        if e.code == 400:
            return error_response("ERR_VALIDATION", "Bad request", 400)
        return error_response("ERR_VALIDATION", str(e), e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_VALIDATION", "Unexpected error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
