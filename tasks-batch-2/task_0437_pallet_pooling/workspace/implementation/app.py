"""Pallet Pooling & Returnable Asset API — Flask entry point.

In-memory store only (db.py). No seeding at startup: the store is empty on every
boot and tests build all state via the API surface. The logical clock defaults to
2026-01-01T00:00:00Z (PRD §2.4).
"""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from middleware import get_auth, require_roles

from routes.setup import bp as setup_bp
from routes.assets import bp as assets_bp
from routes.hires import bp as hires_bp
from routes.audits import bp as audits_bp
from routes.vouchers import bp as vouchers_bp
from routes.collections import bp as collections_bp
from routes.invoices import bp as invoices_bp
from routes.forecasts import bp as forecasts_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(setup_bp)
    app.register_blueprint(assets_bp)
    app.register_blueprint(hires_bp)
    app.register_blueprint(audits_bp)
    app.register_blueprint(vouchers_bp)
    app.register_blueprint(collections_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(forecasts_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route. Still apply the validation precedence: a request with
        # bad/missing auth must surface ERR_MISSING_AUTH before path resolution
        # is reported. But an unknown path under valid auth is a not-found.
        try:
            get_auth()
        except ApiError as api_err:
            return error_response(api_err.error_id, api_err.message, api_err.http_status)
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        try:
            get_auth()
        except ApiError as api_err:
            return error_response(api_err.error_id, api_err.message, api_err.http_status)
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Malformed JSON and similar -> treat as a bad request.
        return error_response("ERR_INVALID_REQUEST", str(e.description), 400)

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
