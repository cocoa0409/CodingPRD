"""Crypto Exchange Wallet API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response

from routes.accounts import bp as accounts_bp
from routes.assets import bp as assets_bp
from routes.deposits import bp as deposits_bp
from routes.withdrawal_addresses import bp as withdrawal_addresses_bp
from routes.withdrawals import bp as withdrawals_bp
from routes.orders import bp as orders_bp
from routes.staking import bp as staking_bp
from routes.ledger import bp as ledger_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(accounts_bp)
    app.register_blueprint(assets_bp)
    app.register_blueprint(deposits_bp)
    app.register_blueprint(withdrawal_addresses_bp)
    app.register_blueprint(withdrawals_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(staking_bp)
    app.register_blueprint(ledger_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Malformed JSON etc. surface as 400 from werkzeug; normalise to our envelope.
        if e.code == 404:
            return error_response("ERR_NOT_FOUND", 404, "Resource not found")
        return error_response("ERR_INVALID_REQUEST", 422, e.description or "Invalid request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", 422, "Unexpected error: %s" % e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer waitress: a production WSGI server that tolerates the rapid
    # connect/close churn of per-test-server isolation (the harness reboots the
    # server before every test, 8 rounds concurrently) far better than the
    # single-process Werkzeug dev server, which can drop connections under that
    # load and surface as ConnectionResetError in the test client.
    try:
        from waitress import serve
        # Tests are sequential within a single per-test server, so a small
        # thread pool is plenty; fewer threads means lighter boot/teardown under
        # 8x concurrent rounds.
        serve(app, host="0.0.0.0", port=port, threads=4,
              connection_limit=200, channel_timeout=120, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
