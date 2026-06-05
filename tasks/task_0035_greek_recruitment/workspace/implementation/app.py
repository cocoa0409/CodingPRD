from __future__ import annotations

"""Greek Recruitment API — Flask entry point.

Boots cleanly from a fresh process. The in-memory store starts empty; every entity
the test harness needs is created via the declared API surface.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import errors as E
import response
from routes.bid_matches import bp as bid_matches_bp
from routes.chapters import bp as chapters_bp
from routes.clock import bp as clock_bp
from routes.invitations import bp as invitations_bp
from routes.parties import bp as parties_bp
from routes.pnms import bp as pnms_bp
from routes.preferences import bp as preferences_bp
from routes.risk_incidents import bp as risk_incidents_bp
from routes.rounds import bp as rounds_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(chapters_bp)
    app.register_blueprint(pnms_bp)
    app.register_blueprint(rounds_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(invitations_bp)
    app.register_blueprint(preferences_bp)
    app.register_blueprint(bid_matches_bp)
    app.register_blueprint(risk_incidents_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(E.APIError)
    def handle_api_error(err: E.APIError):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return response.error(
            E.ERR_RESOURCE_NOT_FOUND,
            "Resource or route not found.",
            404,
        )

    @app.errorhandler(405)
    def handle_405(err):
        return response.error(
            E.ERR_INVALID_REQUEST,
            "Method not allowed.",
            405,
        )

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        # Default fallback for any other werkzeug HTTPException.
        return response.error(
            E.ERR_INVALID_REQUEST,
            err.description or "Request error.",
            err.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_uncaught(err: Exception):
        # Don't leak internals; surface as a generic 500.
        return response.error(
            E.ERR_INVALID_REQUEST,
            "Internal server error.",
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
