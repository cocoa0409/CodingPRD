"""Legal Time, Billing & Trust API — Flask entry point.

In-memory only; a fresh process boots an empty store. No seeding at startup.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.reference import bp as reference_bp
from routes.clients import bp as clients_bp
from routes.matters import bp as matters_bp
from routes.entries import bp as entries_bp
from routes.invoices import bp as invoices_bp
from routes.trust import bp as trust_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(matters_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(trust_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route -> standard not-found envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Bad request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        # Surface unexpected server faults as a generic 400 (deterministic
        # malformed-input handling). Should not normally fire.
        return error_response("ERR_INVALID_REQUEST", "Unexpected error.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
