"""SBA 7(a)/504 Loan Origination API — entry point.

Registers all route blueprints and the global error handlers that wrap every
response in the §2.2 envelope. In-memory store only; nothing is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.lenders import bp as lenders_bp
from routes.borrowers import bp as borrowers_bp
from routes.applications import bp as applications_bp
from routes.proceeds import bp as proceeds_bp
from routes.collateral import bp as collateral_bp
from routes.form_packages import bp as form_packages_bp
from routes.credit_memos import bp as credit_memos_bp
from routes.disbursements import bp as disbursements_bp
from routes.guaranty_sales import bp as guaranty_sales_bp
from routes.servicing_reports import bp as servicing_reports_bp
from routes.liquidations import bp as liquidations_bp
from routes.guaranty_purchases import bp as guaranty_purchases_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        lenders_bp, borrowers_bp, applications_bp, proceeds_bp, collateral_bp,
        form_packages_bp, credit_memos_bp, disbursements_bp, guaranty_sales_bp,
        servicing_reports_bp, liquidations_bp, guaranty_purchases_bp,
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
        # Any other werkzeug HTTP error (e.g. 400 bad JSON before our handlers).
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
