"""Flask entrypoint for the EV charging operations API."""

import os
import traceback

from flask import Flask, jsonify

from errors import APIError
from response import error_response

# Blueprints
from routes.audit import bp as audit_bp
from routes.faults import bp as faults_bp
from routes.harness import bp as harness_bp
from routes.members import bp as members_bp
from routes.operators import bp as operators_bp
from routes.payouts import bp as payouts_bp
from routes.piles import bp as piles_bp
from routes.pricing import bp as pricing_bp
from routes.queue import bp as queue_bp
from routes.reservations import bp as reservations_bp
from routes.sessions import bp as sessions_bp
from routes.stations import bp as stations_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(operators_bp)
    app.register_blueprint(stations_bp)
    app.register_blueprint(piles_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(pricing_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(queue_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(faults_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(harness_bp)

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response("ERR_NOT_FOUND", "route not found", 404)

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(_err):
        return error_response("ERR_VALIDATION", "bad request", 422)

    @app.errorhandler(Exception)
    def handle_unhandled(err: Exception):
        # Log unexpected exceptions and surface as validation/internal error.
        traceback.print_exc()
        return error_response("ERR_VALIDATION", f"internal error: {err}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
