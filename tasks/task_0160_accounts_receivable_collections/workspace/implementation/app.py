"""Accounts Receivable & Collections API — entry point.

Registers blueprints, error handlers, and the health probe. In-memory store
(db.py) starts empty on every boot; NOTHING is seeded here.
"""
import os

from flask import Flask, jsonify

from errors import ApiError, HTTP_STATUS, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response, success

from routes.customers import bp as customers_bp
from routes.invoices import bp as invoices_bp
from routes.payments import bp as payments_bp
from routes.disputes import bp as disputes_bp
from routes.promises import bp as promises_bp
from routes.writeoffs import bp as writeoffs_bp
from routes.dunning import bp as dunning_bp
from routes.statements import bp as statements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(promises_bp)
    app.register_blueprint(writeoffs_bp)
    app.register_blueprint(dunning_bp)
    app.register_blueprint(statements_bp)

    @app.route("/ar/health", methods=["GET"])
    def health():
        return success({"status": "ok"}, status=200)

    @app.route("/health", methods=["GET"])
    def health_root():
        return success({"status": "ok"}, status=200)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route -> ERR_NOT_FOUND envelope.
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(ERR_INVALID_REQUEST, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        # Surface unexpected server errors as a generic 500 envelope.
        body = {
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
        }
        resp = jsonify(body)
        resp.status_code = 500
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
