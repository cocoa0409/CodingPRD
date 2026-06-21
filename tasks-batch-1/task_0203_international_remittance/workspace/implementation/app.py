"""International Remittance API — Flask entry point.

Registers all route blueprints, installs the standard error envelope, and boots
on 0.0.0.0:$PORT in the foreground. All state is in-memory (db.py); a fresh
process boot wipes everything. No entities are seeded at startup.
"""
import os

from flask import Flask

from errors import ApiError, ERROR_STATUS
from response import error as error_response
from routes.config import bp as config_bp
from routes.parties import bp as parties_bp
from routes.quotes import bp as quotes_bp
from routes.transfers import bp as transfers_bp
from routes.compliance import bp as compliance_bp
from routes.payouts import bp as payouts_bp
from routes.refunds import bp as refunds_bp
from routes.ledger import bp as ledger_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(compliance_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(refunds_bp)
    app.register_blueprint(ledger_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        # Unknown route — still respond in the standard error envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found",
                              ERROR_STATUS["ERR_NOT_FOUND"])

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed",
                              ERROR_STATUS["ERR_NOT_FOUND"])

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Never leak a stack trace; surface as a generic invalid-request.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc),
                              ERROR_STATUS["ERR_INVALID_REQUEST"])

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
