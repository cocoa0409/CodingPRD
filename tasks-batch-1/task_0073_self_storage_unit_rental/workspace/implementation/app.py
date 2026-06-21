import os

from flask import Flask, request

from errors import ApiError
from response import error_response
from db import db

from routes.facilities import bp as facilities_bp
from routes.units import bp as units_bp
from routes.tenants import bp as tenants_bp
from routes.leases import bp as leases_bp
from routes.invoices import bp as invoices_bp
from routes.payments import bp as payments_bp
from routes.ledger import bp as ledger_bp
from routes.insurance import bp as insurance_bp
from routes.auctions import bp as auctions_bp
from routes.transfers import bp as transfers_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (facilities_bp, units_bp, tenants_bp, leases_bp, invoices_bp,
               payments_bp, ledger_bp, insurance_bp, auctions_bp, transfers_bp,
               clock_bp):
        app.register_blueprint(bp)

    # Serialize all mutating requests to keep in-memory state consistent.
    @app.before_request
    def _acquire_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_VALIDATION", str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
