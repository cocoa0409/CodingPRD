"""Entry point: Flask app, error handlers, blueprint registration.

In-memory store starts EMPTY on every boot (no seeding). The server clock
follows real UTC until a test pins it via POST /_clock/set_current_utc.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response, _meta

import routes_clock
import routes_volunteers
import routes_children
import routes_matches
import routes_lifecycle


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_clock.bp)
    app.register_blueprint(routes_volunteers.bp)
    app.register_blueprint(routes_children.bp)
    app.register_blueprint(routes_matches.bp)
    app.register_blueprint(routes_lifecycle.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / path — surface as the standard not-found envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, HTTPException):
            return error_response("ERR_INVALID_REQUEST", str(e), e.code or 400)
        # Last-resort: standard envelope with a 500.
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
