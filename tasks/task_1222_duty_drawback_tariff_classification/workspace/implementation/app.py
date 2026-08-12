"""Duty Drawback & Tariff Classification API — entry point.

All endpoints are mounted under /customs. The store starts empty on every
boot; the logical clock defaults to exactly 2026-05-01T00:00:00Z.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response, success_object


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.clients import bp as clients_bp
    from routes.classifications import bp as classifications_bp
    from routes.rulings import bp as rulings_bp
    from routes.entries import bp as entries_bp
    from routes.exports import bp as exports_bp
    from routes.claims import bp as claims_bp
    from routes.measures import bp as measures_bp
    from routes.invoices import bp as invoices_bp
    from routes.audits import bp as audits_bp
    from routes.records import bp as records_bp
    from routes.ops import bp as ops_bp

    for bp in (
        clients_bp, classifications_bp, rulings_bp, entries_bp, exports_bp,
        claims_bp, measures_bp, invoices_bp, audits_bp, records_bp, ops_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", 500, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
