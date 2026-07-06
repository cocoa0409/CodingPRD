"""Prosthetics & Orthotics Practice API — entry point, error handlers, routing.

In-memory only. State is wiped on every fresh boot (start.sh re-invocation).
No seeding/preloading of any entity data at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.onboarding import bp as onboarding_bp
from routes.prescriptions import bp as prescriptions_bp
from routes.device_orders import bp as device_orders_bp
from routes.milestones import bp as milestones_bp
from routes.prior_auths import bp as prior_auths_bp
from routes.claim_lines import bp as claim_lines_bp
from routes.repairs import bp as repairs_bp
from routes.adjustments import bp as adjustments_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(onboarding_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(device_orders_bp)
    app.register_blueprint(milestones_bp)
    app.register_blueprint(prior_auths_bp)
    app.register_blueprint(claim_lines_bp)
    app.register_blueprint(repairs_bp)
    app.register_blueprint(adjustments_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route / unresolved path -> resource not found.
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed for this resource.", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, HTTPException):
            return error_response("ERR_INVALID_REQUEST", str(err), err.code or 400)
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % err, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
