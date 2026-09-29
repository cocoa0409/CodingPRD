"""Vendor Chargeback & Supplier Compliance Program API.

Flask application factory and error plumbing. All state lives in the
in-memory store in core.py, which starts empty on every boot and is never
seeded, so re-invoking start.sh wipes the world.
"""

import os

from flask import Flask, jsonify

from core import ApiError, error_response
import routes_disputes
import routes_money
import routes_performance
import routes_program
import routes_reads
import routes_supply


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_reads.bp)
    app.register_blueprint(routes_program.bp)
    app.register_blueprint(routes_supply.bp)
    app.register_blueprint(routes_disputes.bp)
    app.register_blueprint(routes_performance.bp)
    app.register_blueprint(routes_money.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(error_response(error.error_id, error.message)), error.http_status

    @app.errorhandler(404)
    def handle_not_found(_error):
        return (
            jsonify(error_response("ERR_INVALID_REQUEST", "Unknown resource path.")),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return (
            jsonify(
                error_response("ERR_INVALID_REQUEST", "Method not allowed on this path.")
            ),
            405,
        )

    @app.errorhandler(400)
    def handle_bad_request(_error):
        return (
            jsonify(error_response("ERR_INVALID_REQUEST", "Malformed request.")),
            400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return handle_api_error(error)
        return (
            jsonify(error_response("ERR_INVALID_REQUEST", "Unexpected server error.")),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
