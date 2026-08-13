"""Hospital Price Transparency API — Flask entry point.

In-memory only; the store starts empty on every boot (per-test-server
isolation re-launches start.sh before every test). No seeding, no disk state.
"""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.facilities import bp as facilities_bp
from routes.payers import bp as payers_bp
from routes.contracts import bp as contracts_bp
from routes.items import bp as items_bp
from routes.records import bp as records_bp
from routes.rates import bp as rates_bp
from routes.lists import bp as lists_bp
from routes.cycles import bp as cycles_bp
from routes.files import bp as files_bp
from routes.discrepancies import bp as discrepancies_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(facilities_bp)
    app.register_blueprint(payers_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(records_bp)
    app.register_blueprint(rates_bp)
    app.register_blueprint(lists_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(discrepancies_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
