"""Aquarium & Pond Maintenance API — Flask entry point.

In-memory only. The store starts EMPTY on every boot; nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.contracts import bp as contracts_bp
from routes.systems import bp as systems_bp
from routes.technicians import bp as technicians_bp
from routes.visits import bp as visits_bp
from routes.invoices import bp as invoices_bp
from routes.installs import bp as installs_bp
from routes.emergencies import bp as emergencies_bp
from routes.quarantines import bp as quarantines_bp
from routes.repairs import bp as repairs_bp
from routes.feeding_plans import bp as feeding_plans_bp, clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(contracts_bp)
    app.register_blueprint(systems_bp)
    app.register_blueprint(technicians_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(installs_bp)
    app.register_blueprint(emergencies_bp)
    app.register_blueprint(quarantines_bp)
    app.register_blueprint(repairs_bp)
    app.register_blueprint(feeding_plans_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        # method not allowed on an existing path
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http(err):
        if isinstance(err, ApiError):
            return handle_api_error(err)
        status = err.code or 500
        if status == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request.", 422)
        return error_response("ERR_INVALID_REQUEST", err.description or "Error.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return handle_api_error(err)
        return error_response("ERR_INVALID_REQUEST", "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
