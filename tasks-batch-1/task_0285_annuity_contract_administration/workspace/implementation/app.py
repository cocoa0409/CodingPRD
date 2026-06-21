"""Annuity Contract Administration API — Flask entry point.

In-memory storage only (see db.py); the store is empty on every boot. No
entity data is seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from clock import iso8601
from db import store
from errors import ApiError
from response import error_response

# Route blueprints
from routes.products import bp as products_bp
from routes.contracts import bp as contracts_bp
from routes.premiums import bp as premiums_bp
from routes.allocations import bp as allocations_bp
from routes.index_segments import bp as index_segments_bp
from routes.crediting_events import bp as crediting_events_bp
from routes.withdrawals import bp as withdrawals_bp
from routes.beneficiaries import bp as beneficiaries_bp
from routes.annuitizations import bp as annuitizations_bp
from routes.death_claims import bp as death_claims_bp
from routes.exchanges import bp as exchanges_bp
from routes.clock_routes import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(products_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(premiums_bp)
    app.register_blueprint(allocations_bp)
    app.register_blueprint(index_segments_bp)
    app.register_blueprint(crediting_events_bp)
    app.register_blueprint(withdrawals_bp)
    app.register_blueprint(beneficiaries_bp)
    app.register_blueprint(annuitizations_bp)
    app.register_blueprint(death_claims_bp)
    app.register_blueprint(exchanges_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status, store.clock.now())

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route — emit the standard not-found envelope.
        return error_response(
            "ERR_RESOURCE_NOT_FOUND",
            "The requested resource was not found.",
            404,
            store.clock.now(),
        )

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(
            "ERR_RESOURCE_NOT_FOUND",
            "Method not allowed for this resource.",
            404,
            store.clock.now(),
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Let already-handled HTTP exceptions pass through their own handlers.
        if isinstance(err, HTTPException):
            return err
        return error_response(
            "ERR_INVALID_REQUEST",
            "An unexpected error occurred.",
            500,
            store.clock.now(),
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve through waitress — a production-grade WSGI server that handles
    # concurrent connections reliably. The Werkzeug development server can drop
    # connections (BadStatusLine on the client) under the heavy concurrent load
    # of the parallel per-test-server sweep; waitress does not.
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
