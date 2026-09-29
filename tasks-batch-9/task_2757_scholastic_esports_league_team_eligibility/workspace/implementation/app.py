"""Scholastic Esports League eligibility API.

In-memory only: every boot starts with a completely empty store, no entity data
is ever seeded, and the logical league clock starts at 2026-08-01T00:00:00.000Z.
"""

import os

from flask import Flask, jsonify

import routes_a
import routes_b
import routes_c
import routes_d
import routes_e
from errors import ApiError
from http_util import api_error_response, error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for module in (routes_a, routes_b, routes_c, routes_d, routes_e):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return api_error_response(exc)

    @app.errorhandler(404)
    def _not_found(_exc):
        return jsonify(error_body("ERR_NOT_FOUND", "No such route.")), 404

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed for this route.")), 404

    @app.errorhandler(400)
    def _bad_request(_exc):
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "The request body could not be parsed.")),
            400,
        )

    @app.get("/health")
    def _health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
