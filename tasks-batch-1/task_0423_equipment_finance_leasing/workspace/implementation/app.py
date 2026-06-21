"""Equipment Finance & Leasing API — entry point.

Registers all route blueprints and the global error handlers that wrap every
response in the §2.2 envelope. In-memory store only; nothing is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.lessors import bp as lessors_bp
from routes.vendors import bp as vendors_bp
from routes.credit_applications import bp as credit_applications_bp
from routes.lessees import bp as lessees_bp
from routes.leases import bp as leases_bp
from routes.equipment import bp as equipment_bp
from routes.billing import bp as billing_bp
from routes.ucc import bp as ucc_bp
from routes.tax import bp as tax_bp
from routes.add_ons import bp as add_ons_bp
from routes.eot_elections import bp as eot_elections_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        lessors_bp, vendors_bp, credit_applications_bp, lessees_bp, leases_bp,
        equipment_bp, billing_bp, ucc_bp, tax_bp, add_ons_bp, eot_elections_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        # Method not allowed -> treat as not found per the resource-oriented surface.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc):
        code = exc.code or 500
        if code == 400:
            return error_response("ERR_INVALID_REQUEST", "Invalid request", 400)
        return error_response("ERR_INVALID_REQUEST", str(exc), code if 400 <= code < 500 else 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Never leak a stack trace; wrap unexpected errors in the envelope.
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress, a production-grade WSGI server. It boots fast and drains
    # concurrent connections cleanly, which keeps per-test restarts reliable under
    # the runner's high-concurrency sweep (the werkzeug dev server is fragile there,
    # producing BadStatusLine drops and slow boots). Fall back to the dev server if
    # waitress is somehow unavailable.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
