"""Infant Formula & Baby Food Manufacturing API — entry point.

In-memory only: every boot starts with an empty store (no seeding), so the
per-test-server restart harness always sees a clean slate.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_body

API_PREFIX = "/api/v1"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.system import bp as system_bp
    from routes.profiles import bp as profiles_bp
    from routes.suppliers import bp as suppliers_bp
    from routes.formulas import bp as formulas_bp
    from routes.batches import bp as batches_bp
    from routes.labels import bp as labels_bp
    from routes.complaints import bp as complaints_bp
    from routes.recalls import bp as recalls_bp
    from routes.allocations import bp as allocations_bp

    for bp in (system_bp, profiles_bp, suppliers_bp, formulas_bp, batches_bp,
               labels_bp, complaints_bp, recalls_bp, allocations_bp):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_body(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_body("ERR_NOT_FOUND", "The requested resource does not exist", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_body("ERR_NOT_FOUND", "The requested resource does not exist", 404)

    @app.errorhandler(400)
    def handle_400(e):
        if isinstance(e, ApiError):
            return error_body(e.error_id, e.message, e.http_status)
        return error_body("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(500)
    def handle_500(e):
        return error_body("ERR_INVALID_REQUEST", "Internal error: %s" % e, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
