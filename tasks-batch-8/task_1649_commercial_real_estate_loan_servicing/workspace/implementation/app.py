"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

import errors as err
from response import error as error_response
from routes import (
    assumptions, borrowers, clock, covenants, extensions, inspections, insurance,
    leases, loans, properties, reserves, statements, watchlist,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        borrowers.bp, loans.bp, properties.bp, statements.bp, covenants.bp,
        reserves.bp, leases.bp, inspections.bp, insurance.bp, assumptions.bp,
        extensions.bp, watchlist.bp, clock.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(err.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, err.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        import traceback
        traceback.print_exc()
        return error_response(err.ERR_INVALID_REQUEST, str(e), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
