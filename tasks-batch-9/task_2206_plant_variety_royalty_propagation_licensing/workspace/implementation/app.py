"""Plant Variety Royalty & Propagation Licensing API.

A fresh process starts with a completely empty in-memory store and the logical
clock at 2026-08-01T00:00:00Z. Nothing is seeded or persisted anywhere.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body, error_response
from routes.clock import bp as clock_bp
from routes.enforcement import bp as enforcement_bp
from routes.filings import bp as filings_bp
from routes.propagators import bp as propagators_bp
from routes.quotas import bp as quotas_bp
from routes.royalty import bp as royalty_bp
from routes.sublicense import bp as sublicense_bp
from routes.trials import bp as trials_bp
from routes.varieties import bp as varieties_bp

BLUEPRINTS = (
    varieties_bp,
    filings_bp,
    trials_bp,
    propagators_bp,
    quotas_bp,
    royalty_bp,
    sublicense_bp,
    enforcement_bp,
    clock_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "The requested route does not exist.")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return jsonify(error_body(
            "ERR_METHOD_NOT_ALLOWED",
            "The HTTP method is not allowed for this route.")), 405

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return jsonify(error_body(
            "ERR_INVALID_REQUEST",
            "The request body or query string is malformed.")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc)
        return jsonify(error_body(
            "ERR_INTERNAL", "An unexpected server error occurred.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
