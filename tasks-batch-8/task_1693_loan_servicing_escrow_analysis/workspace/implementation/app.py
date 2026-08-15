"""Entry point: app factory, error handlers, route registration."""

import os

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND
from util import error_body

import routes_core
import routes_payees
import routes_disbursements
import routes_insurance
import routes_tax
import routes_analysis
import routes_advances
import routes_error_cases


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for mod in (
        routes_core,
        routes_payees,
        routes_disbursements,
        routes_insurance,
        routes_tax,
        routes_analysis,
        routes_advances,
        routes_error_cases,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify(error_body(ERR_NOT_FOUND, "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_body(ERR_NOT_FOUND, "Method not allowed")), 405

    @app.errorhandler(400)
    def handle_400(e):
        # Malformed JSON bodies etc.
        return jsonify(error_body("ERR_INVALID_REQUEST", "Bad request")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return jsonify(error_body("ERR_INTERNAL", str(e))), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
