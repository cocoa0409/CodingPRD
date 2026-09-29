"""Certified Pre-Owned programme API. In-memory only; no entity data is seeded."""
import os

from flask import Flask, jsonify

import helpers as h
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix="/cpo")

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(h.error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_404(_err):
        return jsonify(h.error_body("ERR_NOT_FOUND", "No such route.")), 404

    @app.errorhandler(405)
    def handle_405(_err):
        return (
            jsonify(
                h.error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed on that route.")
            ),
            405,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return handle_api_error(err)
        status = getattr(err, "code", None)
        if isinstance(status, int) and 400 <= status < 500:
            return (
                jsonify(h.error_body("ERR_INVALID_REQUEST", str(err))),
                status,
            )
        app.logger.exception("unhandled error")
        return jsonify(h.error_body("ERR_INTERNAL", "Unexpected server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
