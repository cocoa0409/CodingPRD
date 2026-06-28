"""Podiatry & Foot-Care Practice API — entry point.

Registers all route blueprints and installs the global error handlers that emit
the standard error envelope (PRD §2.2). In-memory storage only; no seeding.
"""

import os

from flask import Flask

import errors
import response as resp

from routes.provisioning import bp as provisioning_bp
from routes.patients import bp as patients_bp
from routes.prior_authorizations import bp as prior_authorizations_bp
from routes.encounters import bp as encounters_bp
from routes.procedures import bp as procedures_bp
from routes.orthotic_rxs import bp as orthotic_rxs_bp
from routes.lab_orders import bp as lab_orders_bp
from routes.dme_dispenses import bp as dme_dispenses_bp
from routes.imaging_orders import bp as imaging_orders_bp
from routes.referrals import bp as referrals_bp
from routes.recalls import bp as recalls_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(provisioning_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(prior_authorizations_bp)
    app.register_blueprint(encounters_bp)
    app.register_blueprint(procedures_bp)
    app.register_blueprint(orthotic_rxs_bp)
    app.register_blueprint(lab_orders_bp)
    app.register_blueprint(dme_dispenses_bp)
    app.register_blueprint(imaging_orders_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(recalls_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return resp.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        # Unknown route -> standard not-found envelope.
        return resp.error(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return resp.error(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a stack trace; surface a generic envelope.
        if isinstance(err, errors.ApiError):
            return resp.error(err.error_id, err.message, err.http_status)
        return resp.error("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
