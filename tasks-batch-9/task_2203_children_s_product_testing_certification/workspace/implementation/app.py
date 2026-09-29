"""Children's Product Testing & Certification reference implementation.

Storage is entirely in-process: a fresh interpreter starts with an empty
database and a logical clock reading 2026-08-01T00:00:00Z. Nothing is seeded.
"""

import os

from flask import Flask

import response
from errors import ApiError
from routes.batches import bp as batches_bp
from routes.cases import bp as cases_bp
from routes.certificates import bp as certificates_bp
from routes.clock import bp as clock_bp
from routes.events import bp as events_bp
from routes.labs import bp as labs_bp
from routes.orders import bp as orders_bp
from routes.partcerts import bp as partcerts_bp
from routes.plans import bp as plans_bp
from routes.products import bp as products_bp
from routes.reference import bp as reference_bp

API_PREFIX = "/compliance"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (
        clock_bp,
        reference_bp,
        labs_bp,
        products_bp,
        partcerts_bp,
        plans_bp,
        orders_bp,
        certificates_bp,
        batches_bp,
        cases_bp,
        events_bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The requested route does not exist.", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error_response(exc.error_id, exc.message, exc.http_status)
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
