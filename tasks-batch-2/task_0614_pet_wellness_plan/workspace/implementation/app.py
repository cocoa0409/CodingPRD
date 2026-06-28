"""Pet Wellness-Plan Membership API — Flask entry point (PRD).

Boots a fresh in-memory store on every process start (no seeding). Registers
all route blueprints and the global error handlers that wrap every response in
the standard envelope (PRD §2.2).
"""
import os

from flask import Flask, jsonify

from errors import ApiError, HTTP_STATUS, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body

from routes.catalog import bp as catalog_bp
from routes.accounts import bp as accounts_bp
from routes.memberships import bp as memberships_bp
from routes.terms_visits import bp as terms_visits_bp
from routes.system import bp as system_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(memberships_bp)
    app.register_blueprint(terms_visits_bp)
    app.register_blueprint(system_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify(error_body(ERR_NOT_FOUND, "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path -> treat as not found per the
        # catalogue (no dedicated error id).
        return jsonify(error_body(ERR_NOT_FOUND, "Method not allowed")), 404

    @app.errorhandler(400)
    def handle_400(e):
        body = error_body(ERR_INVALID_REQUEST, "Malformed request")
        return jsonify(body), HTTP_STATUS[ERR_INVALID_REQUEST]

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        body = error_body("ERR_INTERNAL", "Internal server error")
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
