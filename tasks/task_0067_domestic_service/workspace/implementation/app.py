"""Flask application entry point for the Domestic Service Dispatch API."""
import os
import sys
import traceback

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import APIError
from response import error_response


def _setup_global_error_handlers(app: Flask):
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_FORBIDDEN", "Method not allowed", 403)

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_VALIDATION_ERROR", "Bad request", 422)

    @app.errorhandler(HTTPException)
    def handle_http(err):
        return error_response(
            "ERR_VALIDATION_ERROR" if err.code == 400 else "ERR_NOT_FOUND",
            err.description or "HTTP error",
            err.code,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc(file=sys.stderr)
        return error_response("ERR_VALIDATION_ERROR", f"Internal error: {err}", 422)


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register blueprints
    from routes.personnel_routes import bp as personnel_bp
    from routes.catalog_routes import bp as catalog_bp
    from routes.order_routes import bp as order_bp
    from routes.claim_routes import bp as claim_bp

    app.register_blueprint(personnel_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(claim_bp)

    _setup_global_error_handlers(app)

    @app.route("/", methods=["GET"])
    def root():
        return jsonify({"service": "domestic-service-dispatch", "status": "ok"}), 200

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
