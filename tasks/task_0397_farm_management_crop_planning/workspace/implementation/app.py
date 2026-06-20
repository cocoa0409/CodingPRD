"""Farm Management & Crop Planning API — Flask entry point.

Registers all resource blueprints and the global error handlers. Storage is
in-memory (see db.py); the store starts EMPTY on every boot — no seeding.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.applicators import bp as applicators_bp
from routes.application_records import bp as application_records_bp
from routes.crop_plans import bp as crop_plans_bp
from routes.equipment import bp as equipment_bp
from routes.harvest_events import bp as harvest_events_bp
from routes.input_products import bp as input_products_bp
from routes.irrigation_events import bp as irrigation_events_bp
from routes.labor_entries import bp as labor_entries_bp
from routes.parcels import bp as parcels_bp
from routes.planting_events import bp as planting_events_bp
from routes.sale_contracts import bp as sale_contracts_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        parcels_bp,
        crop_plans_bp,
        input_products_bp,
        application_records_bp,
        planting_events_bp,
        harvest_events_bp,
        sale_contracts_bp,
        equipment_bp,
        labor_entries_bp,
        irrigation_events_bp,
        applicators_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map any other werkzeug HTTP error (e.g. malformed body) to a
        # standard envelope. Bad request shapes surface as ERR_INVALID_REQUEST.
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)
        if e.code in (401,):
            return error_response("ERR_UNAUTHENTICATED", "Unauthenticated.", 401)
        if e.code in (403,):
            return error_response("ERR_FORBIDDEN", "Forbidden.", 403)
        return error_response("ERR_INVALID_REQUEST", e.description or "Error.", e.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Last-resort guard so the server never returns a non-enveloped 500.
        return error_response("ERR_INVALID_REQUEST", "Unexpected error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
