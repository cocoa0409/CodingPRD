"""Flask entry point for the Auto Title & Tag DMV Runner API.

Wires every blueprint, registers the standard response-envelope error handlers,
and runs the server in the foreground on 0.0.0.0:$PORT (default 10000). The
in-memory store starts EMPTY on every boot — no seeding, no preloaded entities.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.config import bp as config_bp
from routes.fee_schedules import bp as fee_schedules_bp
from routes.accounts import bp as accounts_bp
from routes.transactions import bp as transactions_bp
from routes.documents import bp as documents_bp
from routes.fee_quotes import bp as fee_quotes_bp
from routes.submissions import bp as submissions_bp
from routes.runner_trips import bp as runner_trips_bp
from routes.lien_packets import bp as lien_packets_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(fee_schedules_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(fee_quotes_bp)
    app.register_blueprint(submissions_bp)
    app.register_blueprint(runner_trips_bp)
    app.register_blueprint(lien_packets_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
