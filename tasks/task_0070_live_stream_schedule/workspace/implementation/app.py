"""Entry point — registers blueprints, error handlers, and starts Flask."""

import logging
import os

from flask import Flask, jsonify

from errors import APIError
from response import error as error_response

from routes.streamers import bp as streamers_bp
from routes.studios import bp as studios_bp
from routes.products import bp as products_bp
from routes.applications import bp as applications_bp
from routes.violations import bp_v as violations_bp, bp_a as appeals_bp
from routes.settlements import bp as settlements_bp
from routes.audit_logs import bp as audit_logs_bp
from routes.admin import bp as admin_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # ------------------------------------------------------------------
    # Error handlers — every error response must use the standard envelope.
    # ------------------------------------------------------------------
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_):
        return error_response("ERR_NOT_FOUND",
                              "Method not allowed for this resource", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_VALIDATION_FAILED", str(err), 422)

    @app.errorhandler(Exception)
    def handle_500(err: Exception):
        app.logger.exception("Unhandled server error")
        return error_response("ERR_VALIDATION_FAILED", str(err), 422)

    # ------------------------------------------------------------------
    # Blueprints
    # ------------------------------------------------------------------
    app.register_blueprint(streamers_bp)
    app.register_blueprint(studios_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(violations_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(audit_logs_bp)
    app.register_blueprint(admin_bp)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
