"""Hospital Revenue Cycle Management API — entry point.

In-memory storage only (see db.py). No seeding/preloading: the store starts
empty on every boot and every entity is created by tests via the declared
endpoints. start.sh re-invocation starts a fresh process, wiping all state."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.reference import bp as reference_bp
from routes.encounters import bp as encounters_bp
from routes.coding import bp as coding_bp
from routes.claims import bp as claims_bp
from routes.statements import bp as statements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(encounters_bp)
    app.register_blueprint(coding_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(statements_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unmatched route -> treat as a missing resource.
        return response.error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return response.error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, HTTPException):
            return response.error_response(
                "ERR_INVALID_REQUEST", err.description or "Bad request.", err.code or 400
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", "An unexpected error occurred.", 400
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
