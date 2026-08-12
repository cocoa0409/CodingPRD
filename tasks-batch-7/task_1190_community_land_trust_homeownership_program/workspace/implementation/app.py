"""Flask application entry point.

Binds 0.0.0.0:$PORT (default 10000). All state is in-memory in db.store and
starts empty on every boot; the logical clock starts at 2026-05-01T00:00:00Z.
"""
import os

from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from util import error_envelope

import routes_programs
import routes_households
import routes_education
import routes_units
import routes_leases
import routes_waitlist
import routes_resale
import routes_alias


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_programs,
        routes_households,
        routes_education,
        routes_units,
        routes_leases,
        routes_waitlist,
        routes_resale,
        routes_alias,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        payload, status = error_envelope(exc.error_id, exc.message, exc.status)
        return jsonify(payload), status

    @app.errorhandler(404)
    def handle_404(_exc):
        payload, status = error_envelope(ERR_NOT_FOUND, "Resource not found", 404)
        return jsonify(payload), status

    @app.errorhandler(405)
    def handle_405(_exc):
        payload, status = error_envelope(ERR_INVALID_REQUEST,
                                         "Method not allowed for this path", 405)
        return jsonify(payload), status

    @app.errorhandler(500)
    def handle_500(exc):
        payload, status = error_envelope(ERR_INVALID_REQUEST, "Internal error", 500)
        return jsonify(payload), status

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
