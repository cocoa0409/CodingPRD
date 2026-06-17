"""Custom Cabinetry & Millwork Shop API — entry point.

In-memory storage only; state is wiped on every fresh process boot. No seeding.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

# Route blueprints
import routes_shop
import routes_customer
import routes_project
import routes_spec
import routes_production
import routes_changeorder
import routes_draw
import routes_install
import routes_flat


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_shop.bp)
    app.register_blueprint(routes_customer.bp)
    app.register_blueprint(routes_project.bp)
    app.register_blueprint(routes_spec.bp)
    app.register_blueprint(routes_production.bp)
    app.register_blueprint(routes_changeorder.bp)
    app.register_blueprint(routes_draw.bp)
    app.register_blueprint(routes_install.bp)
    app.register_blueprint(routes_flat.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        # Werkzeug HTTP exceptions carry a code; map 404/405 to ERR_NOT_FOUND.
        code = getattr(e, "code", None)
        if code in (404, 405):
            return error_response("ERR_NOT_FOUND", 404, "Resource not found")
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
