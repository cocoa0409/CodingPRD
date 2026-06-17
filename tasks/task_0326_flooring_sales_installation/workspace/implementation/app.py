"""Flooring Sales & Installation API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.actors import bp as actors_bp
from routes.clock_admin import bp as clock_bp
from routes.crews import bp as crews_bp
from routes.estimates import bp as estimates_bp
from routes.install_slots import bp as install_slots_bp
from routes.jobs import bp as jobs_bp
from routes.material_orders import bp as material_orders_bp
from routes.products import bp as products_bp
from routes.warranty_claims import bp as warranty_claims_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(actors_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(estimates_bp)
    app.register_blueprint(material_orders_bp)
    app.register_blueprint(crews_bp)
    app.register_blueprint(install_slots_bp)
    app.register_blueprint(warranty_claims_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route — map to the catalogue's not-found shape.
        return response.error("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(e):
        return response.error("ERR_NOT_FOUND", 404, "Resource not found.")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Body parsing or other HTTP errors -> 422 invalid request envelope.
        status = e.code or 500
        if status == 400:
            return response.error("ERR_INVALID_REQUEST", 422, "Malformed request.")
        return response.error("ERR_INVALID_REQUEST", status if status >= 400 else 422, str(e))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return response.error("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
