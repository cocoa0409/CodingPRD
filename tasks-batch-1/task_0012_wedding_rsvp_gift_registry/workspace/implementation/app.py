"""Wedding RSVP & Gift Registry API — Flask entry point.

Boots with empty in-memory stores. The test harness restarts this process
before every test, so there is no carry-over state.
"""
from __future__ import annotations

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.clock import bp as clock_bp
from routes.weddings import bp as weddings_bp
from routes.meal_options import bp as meal_options_bp
from routes.tables import bp as tables_bp
from routes.guests import bp as guests_bp
from routes.plus_ones import bp as plus_ones_bp
from routes.seating_assignments import bp as seating_bp
from routes.registry_items import bp as registry_items_bp
from routes.purchases import bp as purchases_bp
from routes.thank_you_notes import bp as thank_you_bp


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(clock_bp)
    app.register_blueprint(weddings_bp)
    app.register_blueprint(meal_options_bp)
    app.register_blueprint(tables_bp)
    app.register_blueprint(guests_bp)
    app.register_blueprint(plus_ones_bp)
    app.register_blueprint(seating_bp)
    app.register_blueprint(registry_items_bp)
    app.register_blueprint(purchases_bp)
    app.register_blueprint(thank_you_bp)

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ERR_NOT_FOUND, "Route not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        # Per PRD §2.9 / §1.4 we surface unknown method/path uniformly as
        # ERR_NOT_FOUND at 404.
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def _bad_request(e):
        return error_response(ERR_INVALID_REQUEST, str(e), 400)

    @app.errorhandler(Exception)
    def _internal(e):
        if isinstance(e, HTTPException):
            return error_response(ERR_INVALID_REQUEST, e.description or str(e), e.code or 500)
        # Log to stderr so the test harness can see it.
        print(f"Unhandled error: {type(e).__name__}: {e}", file=sys.stderr)
        return error_response("ERR_INTERNAL", f"Internal error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
