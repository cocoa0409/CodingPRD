"""Flask application entry point.

Boots a fresh, empty in-memory store on every process start. No entity is
seeded, preloaded, or hardcoded -- every entity is created by tests through
the declared API surface.
"""
from __future__ import annotations

import os

from flask import Flask

from errors import APIError, ERR_VALIDATION, ERR_NOT_FOUND, ERR_FORBIDDEN
from response import error as error_response

from routes.cap_tables import bp as cap_tables_bp
from routes.security_classes import bp as security_classes_bp
from routes.shareholders import bp as shareholders_bp
from routes.share_issuances import bp as share_issuances_bp
from routes.valuations import bp as valuations_bp
from routes.option_pools import bp as option_pools_bp
from routes.option_grants import bp as option_grants_bp
from routes.exercises import bp as exercises_bp
from routes.forms_3921 import bp as forms_3921_bp
from routes.elections import bp as elections_bp
from routes.safe_notes import bp as safe_notes_bp
from routes.liquidation import bp as liquidation_bp
from routes.blackout_windows import bp as blackout_windows_bp
from routes.clock import bp as clock_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        cap_tables_bp, security_classes_bp, shareholders_bp, share_issuances_bp,
        valuations_bp, option_pools_bp, option_grants_bp, exercises_bp,
        forms_3921_bp, elections_bp, safe_notes_bp, liquidation_bp,
        blackout_windows_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response(ERR_NOT_FOUND, "Route not found.", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response(ERR_FORBIDDEN, "Method not allowed.", 405)

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response(ERR_VALIDATION, "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_other(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        msg = f"Internal error: {type(e).__name__}: {e}"
        return error_response(ERR_VALIDATION, msg, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
