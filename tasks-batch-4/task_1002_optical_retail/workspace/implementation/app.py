"""Optical Retail & Eyewear API -- entry point.

All routes are mounted under /optical. Storage is in-memory and starts EMPTY on
every boot: nothing is seeded, preloaded, or hardcoded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes.catalog import bp as catalog_bp
from routes.exams import bp as exams_bp
from routes.insurance import bp as insurance_bp
from routes.kits import bp as kits_bp
from routes.lab import bp as lab_bp
from routes.orders import bp as orders_bp
from routes.prescriptions import bp as prescriptions_bp
from routes.warranty import bp as warranty_bp

API_PREFIX = "/optical"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        catalog_bp,
        prescriptions_bp,
        kits_bp,
        exams_bp,
        orders_bp,
        lab_bp,
        insurance_bp,
        warranty_bp,
    ):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", 404, "Resource not found.")
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed.")
        return error_response(
            "ERR_INVALID_REQUEST", exc.code or 400, exc.description or "Bad request."
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", 400, str(exc))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
