"""Implant Device UDI Tracking API — entry point.

Storage is in-memory only and starts completely empty on every boot; no entity
is ever seeded, preloaded or hardcoded here.  Tests build all state through the
declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ERROR_STATUS, ApiError
from routes.clinical import bp as clinical_bp
from routes.compliance import bp as compliance_bp
from routes.explants import bp as explants_bp
from routes.inventory import bp as inventory_bp
from routes.master import bp as master_bp
from routes.ops import bp as ops_bp
from routes.records import bp as records_bp
from routes.revenue import bp as revenue_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        master_bp,
        inventory_bp,
        clinical_bp,
        records_bp,
        revenue_bp,
        compliance_bp,
        explants_bp,
        ops_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error_response("ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
