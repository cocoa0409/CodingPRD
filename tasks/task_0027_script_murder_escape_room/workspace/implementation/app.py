"""Flask application entry point."""
import os
import traceback

from flask import Flask

from errors import APIError, ERR_INVALID_REQUEST
from response import error_response

# Routes
from routes.venues import venues_bp
from routes.themes import themes_bp
from routes.slots import slots_bp
from routes.bookings import bookings_bp
from routes.players import players_bp
from routes.staff import staff_bp
from routes.reviews import reviews_bp
from routes.settlement import settlement_bp
from routes.system import system_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_INVALID_REQUEST", "route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_exception(e):
        # Surface JSON parse errors as ERR_INVALID_REQUEST
        try:
            from werkzeug.exceptions import HTTPException
            if isinstance(e, HTTPException):
                return error_response("ERR_INVALID_REQUEST", str(e), e.code or 400)
        except Exception:
            pass
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "internal error", 500)

    app.register_blueprint(venues_bp)
    app.register_blueprint(themes_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(players_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(settlement_bp)
    app.register_blueprint(system_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
