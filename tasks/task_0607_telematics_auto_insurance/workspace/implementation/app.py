"""Telematics Auto Insurance API — Flask entry point.

In-memory only: the store (db.py) starts EMPTY on every boot and no entity is
seeded, preloaded, or hardcoded. State fully resets on each fresh process.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import clock
from errors import ApiError
from response import error_response

# Route blueprints
from routes.clock_routes import bp as clock_bp
from routes.rate_plans import bp as rate_plans_bp
from routes.drivers import bp as drivers_bp
from routes.enrollments import bp as enrollments_bp
from routes.quotes import bp as quotes_bp
from routes.policies import bp as policies_bp
from routes.trips import bp as trips_bp
from routes.statements import bp as statements_bp
from routes.renewals import bp as renewals_bp
from routes.claims import bp as claims_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Reset the logical clock at app construction so a fresh process boots at the
    # default instant (PRD §2.4). The data store is empty by module-init.
    clock.reset()

    app.register_blueprint(clock_bp)
    app.register_blueprint(rate_plans_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(statements_bp)
    app.register_blueprint(renewals_bp)
    app.register_blueprint(claims_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # An unmatched route -> ERR_NOT_FOUND (PRD §2.5).
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(HTTPException)
    def handle_http(err):
        # Malformed body / generic client error -> ERR_VALIDATION (PRD §2.5).
        if err.code and 400 <= err.code < 500:
            return error_response("ERR_VALIDATION", "The request could not be processed.", 422)
        return error_response("ERR_VALIDATION", "Internal error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_VALIDATION", "The request could not be processed.", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
