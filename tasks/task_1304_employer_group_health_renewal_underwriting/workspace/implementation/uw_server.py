"""Entry point: app factory, error handlers, route registration."""
import os

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_body
from routes import register_routes
from services.workflow import expire_quotes


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    register_routes(app)

    @app.before_request
    def _quote_expiry_sweep():
        # Quote expiry is evaluated against the logical clock whenever
        # time-dependent operations are evaluated (PRD 2.8).
        expire_quotes()
        return None

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.status

    @app.errorhandler(404)
    def handle_not_found(err):
        return jsonify(error_body(ERR_NOT_FOUND, "Referenced resource does not exist")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return jsonify(error_body(ERR_INVALID_REQUEST, "Method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return jsonify(error_body(ERR_INVALID_REQUEST, "Unexpected server error")), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
