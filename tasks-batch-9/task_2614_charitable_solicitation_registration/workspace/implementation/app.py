"""Charitable Solicitation Registration API -- application entry point.

The store is in-memory and starts empty on every boot: nothing is seeded,
preloaded or hardcoded, and the logical clock resets to its documented default
(PRD 2.4) with the process.  The harness restarts this server before every test.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.config import bp as config_bp
from routes.enforcement import bp as enforcement_bp
from routes.fundraisers import bp as fundraisers_bp
from routes.organizations import bp as organizations_bp
from routes.promotions import bp as promotions_bp
from routes.registrations import bp as registrations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(config_bp)
    app.register_blueprint(organizations_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(fundraisers_bp)
    app.register_blueprint(promotions_bp)
    app.register_blueprint(enforcement_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(response.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Malformed routes and unsupported methods are reported through the same
        # envelope as every other failure (PRD 2.2).
        return (jsonify(response.error_body("ERR_INVALID_REQUEST",
                                           exc.description or "Invalid request.")),
                exc.code or 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return jsonify(response.error_body("ERR_INVALID_REQUEST", str(exc))), 422

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
