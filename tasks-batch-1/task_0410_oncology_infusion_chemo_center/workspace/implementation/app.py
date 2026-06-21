"""Oncology Infusion & Chemotherapy Center API — entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.patients import bp as patients_bp
from routes.protocols import bp as protocols_bp
from routes.resources import bp as resources_bp
from routes.prior_auth import bp as prior_auth_bp
from routes.cycles import bp as cycles_bp
from routes.drug_orders import bp as drug_orders_bp
from routes.appointments import bp as appointments_bp
from routes.toxicity import bp as toxicity_bp

API_PREFIX = "/infusion-center"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        patients_bp,
        protocols_bp,
        resources_bp,
        prior_auth_bp,
        cycles_bp,
        drug_orders_bp,
        appointments_bp,
        toxicity_bp,
    ):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — keep the standard envelope shape.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return error_response("ERR_HTTP_%d" % exc.code, exc.description or "HTTP error", exc.code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
