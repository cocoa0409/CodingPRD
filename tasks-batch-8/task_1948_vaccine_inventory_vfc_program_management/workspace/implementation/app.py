"""Vaccine Inventory & VFC Program Management API — Flask entry point.

In-memory only. Boots with an empty store and the logical clock fixed at
2026-08-01T00:00:00Z. Listens on 0.0.0.0:$PORT (default 10000).
"""

import os
from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__)

    from routes.provider_sites import bp as provider_sites_bp
    from routes.storage import bp as storage_bp
    from routes.products_lots import bp as products_lots_bp
    from routes.patients_screenings import bp as patients_bp
    from routes.doses import bp as doses_bp
    from routes.orders import bp as orders_bp
    from routes.borrow_tickets import bp as borrow_bp
    from routes.transfers import bp as transfers_bp
    from routes.audits import bp as audits_bp
    from routes.clock import bp as clock_bp

    for bp in (
        provider_sites_bp,
        storage_bp,
        products_lots_bp,
        patients_bp,
        doses_bp,
        orders_bp,
        borrow_bp,
        transfers_bp,
        audits_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Referenced id does not exist", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed for this path", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Malformed JSON body etc. should surface as a 400, not a 500, whenever
        # Flask's JSON parser is the source.
        from werkzeug.exceptions import BadRequest
        if isinstance(err, BadRequest):
            return error_response(ERR_INVALID_REQUEST, "Malformed request body", 400)
        return error_response(ERR_INVALID_REQUEST, f"Unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
