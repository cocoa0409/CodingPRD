"""Infusion Suite Scheduling API — Flask application factory and entry point.

State lives entirely in process memory (see db.py); nothing is seeded at boot,
so every fresh launch starts from an empty record set.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from routes.appointments import bp as appointments_bp
from routes.catalog import bp as catalog_bp
from routes.centers import bp as centers_bp
from routes.clinical import bp as clinical_bp
from routes.patients import bp as patients_bp
from routes.reports import bp as reports_bp
from routes.templates import bp as templates_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        centers_bp,
        catalog_bp,
        patients_bp,
        templates_bp,
        appointments_bp,
        clinical_bp,
        reports_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return (
            jsonify(error_body("ERR_NOT_FOUND", "The requested resource does not exist.")),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return (
            jsonify(
                error_body(
                    "ERR_METHOD_NOT_ALLOWED",
                    "The HTTP method is not allowed for this resource.",
                )
            ),
            405,
        )

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "The request body could not be parsed.")),
            400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        if isinstance(exc, ApiError):
            return jsonify(error_body(exc.error_id, exc.message)), exc.http_status
        app.logger.exception("unhandled error: %s", exc)
        return (
            jsonify(error_body("ERR_INTERNAL", "An unexpected internal error occurred.")),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
