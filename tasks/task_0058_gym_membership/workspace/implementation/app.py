"""Gym membership API — entry point."""
import os
from flask import Flask, request

from errors import APIError
from response import error_response
from middleware import extract_auth, VALID_ROLES
from routes.card_types import bp as card_types_bp
from routes.members import bp as members_bp
from routes.cards import bp as cards_bp
from routes.trainers import bp as trainers_bp
from routes.pt_bookings import bp as pt_bp
from routes.groups import bp as groups_bp
from routes.access import bp as access_bp
from routes.payouts import bp as payouts_bp
from routes.operator import bp as operator_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _auth():
        # Skip auth for non-API methods or unknown — but PRD requires auth on all
        # endpoints including operator (with system role).
        try:
            extract_auth()
        except APIError as e:
            return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(APIError)
    def _handle_api_err(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", "route not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def _handle_400(e):
        return error_response("ERR_VALIDATION", "bad request", 422)

    @app.errorhandler(Exception)
    def _handle_other(e):
        # Avoid leaking — return validation-style error
        return error_response("ERR_VALIDATION", str(e), 422)

    app.register_blueprint(card_types_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(cards_bp)
    app.register_blueprint(trainers_bp)
    app.register_blueprint(pt_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(access_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(operator_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
