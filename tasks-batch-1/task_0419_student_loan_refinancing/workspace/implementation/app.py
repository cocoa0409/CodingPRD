"""Entry point: Flask app, error handlers, blueprint registration.

Student Loan Refi API. In-memory only; nothing is seeded at startup. The store
starts empty on every boot — every entity is created by the test suite through
the declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.bootstrap import bp as bootstrap_bp
from routes.applications import bp as applications_bp
from routes.offers import bp as offers_bp
from routes.cosigners import bp as cosigners_bp
from routes.loans import bp as loans_bp
from routes.forbearance import bp as forbearance_bp
from routes.disbursements import bp as disbursements_bp
from routes.audit import bp as audit_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(bootstrap_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(cosigners_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(forbearance_bp)
    app.register_blueprint(disbursements_bp)
    app.register_blueprint(audit_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / path id resolution miss surfaces as ERR_NOT_FOUND.
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "malformed request", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Fall back to the invalid-request envelope for any other HTTP error.
        return error_response("ERR_INVALID_REQUEST", exc.description or "error", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "unexpected error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
