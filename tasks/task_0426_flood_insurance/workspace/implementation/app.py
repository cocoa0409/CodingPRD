"""Flask entry point for the Flood Insurance (NFIP / FEMA) API.

Wires every blueprint, registers the standard error envelope handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000). The in-memory
store starts EMPTY on every boot — no seeding.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.communities import bp as communities_bp
from routes.properties import bp as properties_bp
from routes.elevation_certificates import bp as elevation_certificates_bp
from routes.policies import bp as policies_bp
from routes.policy_transfers import bp as policy_transfers_bp
from routes.claims import bp as claims_bp
from routes.proofs_of_loss import bp as proofs_of_loss_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(communities_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(elevation_certificates_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(policy_transfers_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(proofs_of_loss_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route / unresolved path -> standard ERR_NOT_FOUND envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(errors.ERR_VALIDATION, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
