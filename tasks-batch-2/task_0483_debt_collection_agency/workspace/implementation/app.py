"""Debt Collection Agency API — Flask entry point.

In-memory store only; no seeding at startup. Boots cleanly on every invocation.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.clock_routes import bp as clock_bp
from routes.creditors import bp as creditors_bp
from routes.consumers import bp as consumers_bp
from routes.accounts import bp as accounts_bp
from routes.communication import bp as communication_bp
from routes.disputes import bp as disputes_bp
from routes.arrangements import bp as arrangements_bp
from routes.payments import bp as payments_bp
from routes.bureau import bp as bureau_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(creditors_bp)
    app.register_blueprint(consumers_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(communication_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(arrangements_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(bureau_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_response(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify(error_response("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify(error_response("ERR_NOT_FOUND", "Method not allowed")), 404

    @app.errorhandler(400)
    def handle_400(err):
        return jsonify(error_response("ERR_INVALID_REQUEST", "Bad request")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return jsonify(error_response(err.error_id, err.message)), err.http_status
        return jsonify(error_response("ERR_INVALID_REQUEST", "Internal error: %s" % err)), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
