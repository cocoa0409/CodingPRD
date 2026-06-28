"""Vehicle Service Contract API — entry point.

In-memory storage only. No entity seeding at startup.
"""
import os
from flask import Flask

from errors import ApiError
from response import error_body
from routes.catalog import bp as catalog_bp
from routes.contracts import bp as contracts_bp
from routes.claims import bp as claims_bp
from routes.cancellations import bp as cancellations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(cancellations_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_body(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_body("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_body("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_body(e.error_id, e.http_status, e.message)
        return error_body("ERR_INVALID_REQUEST", 422, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
