"""Shelf Label & Price Accuracy Compliance API — in-memory Flask application.

Storage is process-local Python dicts. Nothing is seeded: every entity is built
through the declared endpoints, so re-launching this process wipes all state.
"""
import os

from flask import Flask, jsonify

import routes_audits
import routes_estate
import routes_files
import routes_reg
from core import ApiError, error_response, meta


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(routes_estate.bp)
    app.register_blueprint(routes_files.bp)
    app.register_blueprint(routes_audits.bp)
    app.register_blueprint(routes_reg.bp)

    def envelope(error_id, message, status):
        return (
            jsonify(
                {
                    "meta": meta(),
                    "response_type": "error",
                    "data": {"error_id": error_id, "message": message},
                }
            ),
            status,
        )

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return envelope("ERR_INVALID_REQUEST", "resource path not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return envelope("ERR_INVALID_REQUEST", "method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(err):
        return envelope("ERR_INVALID_REQUEST", "malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return envelope("ERR_INVALID_REQUEST", "unexpected server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
