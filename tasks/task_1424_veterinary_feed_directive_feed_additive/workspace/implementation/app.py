"""Entry point: Flask app, error handlers, route registration."""

import os
from flask import Flask

import errors
from response import error_response

from routes.onboarding import bp as onboarding_bp
from routes.vcp import bp as vcp_bp
from routes.vfd import bp as vfd_bp
from routes.feed_orders import bp as feed_orders_bp
from routes.shipments import bp as shipments_bp
from routes.acks import bp as acks_bp
from routes.residue import bp as residue_bp
from routes.audit import bp as audit_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        onboarding_bp, vcp_bp, vfd_bp, feed_orders_bp, shipments_bp,
        acks_bp, residue_bp, audit_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Method not allowed", 400)

    @app.errorhandler(500)
    def handle_500(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), debug=False, use_reloader=False)
