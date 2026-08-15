"""Citizenship Naturalization API — Flask entry point."""
import os
import traceback

from flask import Flask, jsonify

from errors import ApiError
from util import error_body

import routes_program
import routes_applicants
import routes_classes
import routes_volunteers
import routes_workshops
import routes_packets
import routes_feewaivers
import routes_cases
import routes_ceremonies
import routes_mocks


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for mod in (routes_program, routes_applicants, routes_classes,
                routes_volunteers, routes_workshops, routes_packets,
                routes_feewaivers, routes_cases, routes_ceremonies,
                routes_mocks):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(400)
    def handle_400(err):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Bad request")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return jsonify(error_body("ERR_INTERNAL", "Internal server error")), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
