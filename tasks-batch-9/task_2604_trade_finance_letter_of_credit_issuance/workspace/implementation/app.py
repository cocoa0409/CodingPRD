"""Trade finance letter-of-credit issuance service.

Flask application factory and process entry point. Storage is process-local
in-memory dicts: nothing is persisted and nothing is seeded, so a fresh boot
always starts from a completely empty store with the logical clock at
2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, jsonify

import routes_amendments
import routes_credits
import routes_ops
import routes_parties
import routes_presentations
import routes_settlement
from errors import ApiError
from response import error_body, error_response

BLUEPRINTS = (
    routes_parties.bp,
    routes_credits.bp,
    routes_amendments.bp,
    routes_presentations.bp,
    routes_settlement.bp,
    routes_ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Request payload is invalid")), 422

    @app.errorhandler(404)
    def _not_found(_exc):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed")), 405

    @app.errorhandler(415)
    def _unsupported_media(_exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Request payload is invalid")), 422

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc)
        return jsonify(error_body("ERR_INTERNAL", str(exc) or "Internal error")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
