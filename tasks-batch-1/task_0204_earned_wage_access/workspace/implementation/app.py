"""Earned Wage Access API — Flask entry point.

In-memory store; no seeding. Boots fresh on every start.sh invocation.
Binds 0.0.0.0:$PORT (default 10000), runs in the foreground.
"""
import os

from flask import Flask, jsonify

import errors
from response import error_response

from routes.employers import bp as employers_bp
from routes.workers import bp as workers_bp
from routes.pay_periods import bp as pay_periods_bp
from routes.time_entries import bp as time_entries_bp
from routes.advances import bp as advances_bp
from routes.repayment_batches import bp as repayment_batches_bp
from routes.statements import bp as statements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(employers_bp)
    app.register_blueprint(workers_bp)
    app.register_blueprint(pay_periods_bp)
    app.register_blueprint(time_entries_bp)
    app.register_blueprint(advances_bp)
    app.register_blueprint(repayment_batches_bp)
    app.register_blueprint(statements_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort guard so the server never returns a non-enveloped 500 HTML page.
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
