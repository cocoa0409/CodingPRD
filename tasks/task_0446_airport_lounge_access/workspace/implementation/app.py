"""Airport Lounge Access API — Flask entry point.

In-memory only. No seeding at startup; every entity is created via the API.
"""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import errors
from response import error_response

from routes.plans import bp as plans_bp
from routes.clock_routes import bp as clock_bp
from routes.lounges import bp as lounges_bp
from routes.members import bp as members_bp
from routes.cards import bp as cards_bp
from routes.visits import bp as visits_bp
from routes.guests import bp as guests_bp
from routes.day_passes import bp as day_passes_bp
from routes.settlements import bp as settlements_bp
from routes.ledger import bp as ledger_bp
from routes.showers import bp as showers_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        plans_bp,
        clock_bp,
        lounges_bp,
        members_bp,
        cards_bp,
        visits_bp,
        guests_bp,
        day_passes_bp,
        settlements_bp,
        ledger_bp,
        showers_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route → ERR_NOT_FOUND.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        if isinstance(e, HTTPException):
            # Map remaining HTTP exceptions through the envelope.
            code = e.code or 500
            if code == 404:
                return error_response("ERR_NOT_FOUND", "Resource not found", 404)
            if code == 400:
                return error_response("ERR_INVALID_REQUEST", "Bad request", 400)
            return error_response("ERR_INVALID_REQUEST", str(e), code)
        # Unexpected server error.
        return error_response("ERR_INVALID_REQUEST", "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
