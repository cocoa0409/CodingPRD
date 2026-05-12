"""Pet Hospital API entry point (PRD §1, §2).

All endpoints mounted under /pet-hospital. Listens on PORT env var
(default 10000), bound to 0.0.0.0.
"""
from __future__ import annotations

import os
import traceback

from flask import Flask, jsonify

from errors import ApiError, ERROR_HTTP
from response import error_response

# Import every route blueprint.
from routes.owners import bp as owners_bp
from routes.pets import bp as pets_bp
from routes.visits import bp as visits_bp
from routes.treatment_records import bp as tr_bp
from routes.lab_reports import bp as lr_bp
from routes.drugs import bp as drugs_bp
from routes.prescriptions import bp as rx_bp
from routes.cages import bp as cages_bp
from routes.bills import bp as bills_bp
from routes.vaccines import bp as vaccines_bp
from routes.events import bp as events_bp


PREFIX = "/pet-hospital"


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    # Register every blueprint at the /pet-hospital prefix.
    app.register_blueprint(owners_bp, url_prefix=PREFIX)
    app.register_blueprint(pets_bp, url_prefix=PREFIX)
    app.register_blueprint(visits_bp, url_prefix=PREFIX)
    app.register_blueprint(tr_bp, url_prefix=PREFIX)
    app.register_blueprint(lr_bp, url_prefix=PREFIX)
    app.register_blueprint(drugs_bp, url_prefix=PREFIX)
    app.register_blueprint(rx_bp, url_prefix=PREFIX)
    app.register_blueprint(cages_bp, url_prefix=PREFIX)
    app.register_blueprint(bills_bp, url_prefix=PREFIX)
    app.register_blueprint(vaccines_bp, url_prefix=PREFIX)
    app.register_blueprint(events_bp, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(e: ApiError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(
            "ERR_NOT_FOUND",
            "Resource not found",
            404,
        )

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(
            "ERR_VALIDATION_FAILED",
            "Method not allowed",
            422,
        )

    @app.errorhandler(Exception)
    def handle_generic(e):
        # Log to stderr but never leak stack traces in the body.
        traceback.print_exc()
        return error_response(
            "ERR_VALIDATION_FAILED",
            f"Internal error: {type(e).__name__}",
            422,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
