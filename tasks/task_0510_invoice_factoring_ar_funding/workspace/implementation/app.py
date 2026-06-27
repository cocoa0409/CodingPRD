"""Invoice Factoring & A/R Funding API — Flask entry point.

In-memory storage only (see db.py). The store starts EMPTY on every boot —
no seeding. The test harness relaunches this process before every test.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error_envelope

from routes.programs import bp as programs_bp
from routes.clients import bp as clients_bp
from routes.debtors import bp as debtors_bp
from routes.relationships import bp as relationships_bp
from routes.invoices import bp as invoices_bp
from routes.collections import bp as collections_bp
from routes.batches import bp as batches_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)

    app.register_blueprint(programs_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(debtors_bp)
    app.register_blueprint(relationships_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(collections_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_envelope(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_envelope(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_envelope(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Malformed JSON etc. surface as 400; map to ERR_INVALID_REQUEST.
        if exc.code == 400:
            return error_envelope(errors.ERR_INVALID_REQUEST,
                                  "Malformed request", 422)
        if exc.code in (401, 403, 404, 409, 412, 422):
            return error_envelope(errors.ERR_INVALID_REQUEST,
                                  exc.description or "Request error", exc.code)
        return error_envelope(errors.ERR_INVALID_REQUEST,
                              exc.description or "Request error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort guard so a bug never leaks an HTML error page.
        return error_envelope("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
