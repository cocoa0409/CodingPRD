"""Ocean Freight NVOCC API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.shippers import bp as shippers_bp
from routes.tariffs import bp as tariffs_bp
from routes.contracts import bp as contracts_bp
from routes.bonds import bp as bonds_bp
from routes.voyages import bp as voyages_bp
from routes.bookings import bp as bookings_bp
from routes.consolidations import bp as consolidations_bp
from routes.assignments import bp as assignments_bp
from routes.bls import bp as bls_bp
from routes.filings import bp as filings_bp
from routes.invoices import bp as invoices_bp
from routes.policies import bp as policies_bp
from routes.claims import bp as claims_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(shippers_bp)
    app.register_blueprint(tariffs_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(bonds_bp)
    app.register_blueprint(voyages_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(consolidations_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(bls_bp)
    app.register_blueprint(filings_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(claims_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
