"""Hunting & Fishing License API — entry point and error handling.

In-memory only; the store starts empty on every boot. No seeding.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.applicants import bp as applicants_bp
from routes.residency import bp as residency_bp
from routes.education import bp as education_bp
from routes.products import bp as products_bp
from routes.seasons import bp as seasons_bp
from routes.draw_pools import bp as draw_pools_bp
from routes.draw_applications import bp as draw_applications_bp
from routes.licenses import bp as licenses_bp
from routes.harvests import bp as harvests_bp
from routes.replacements import bp as replacements_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        applicants_bp, residency_bp, education_bp, products_bp, seasons_bp,
        draw_pools_bp, draw_applications_bp, licenses_bp, harvests_bp,
        replacements_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / path: surface as ERR_NOT_FOUND in the envelope.
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_INVALID_REQUEST, 400, "Bad request")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
