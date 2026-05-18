"""Flask application entry point — Robo-Advisor Tax-Loss Harvesting API."""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from config import HOST, PORT
from errors import ApiError
from response import error as error_response

# Route blueprints.
from routes.accounts import bp as accounts_bp
from routes.clients import bp as clients_bp
from routes.dividends import bp as dividends_bp
from routes.forms_1099b import bp as forms_1099b_bp
from routes.harvest import bp as harvest_bp
from routes.model_portfolios import bp as model_portfolios_bp
from routes.rebalance import bp as rebalance_bp
from routes.securities import bp as securities_bp
from routes.system_endpoints import bp as system_bp
from routes.trades import bp as trades_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(model_portfolios_bp)
    app.register_blueprint(securities_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(trades_bp)
    app.register_blueprint(harvest_bp)
    app.register_blueprint(rebalance_bp)
    app.register_blueprint(dividends_bp)
    app.register_blueprint(forms_1099b_bp)
    app.register_blueprint(system_bp)

    @app.get("/__test__/now")
    def __test_now():
        """Test helper: return the server clock as an ISO 8601 string."""
        from db import store
        from utils import iso_now
        return jsonify({"now": iso_now(store.now())}), 200

    @app.post("/__test__/reset")
    def __test_reset():
        """Wipe all in-memory state between tests."""
        from db import store, DataStore
        with store.lock:
            new_store = DataStore()
            store.clock = new_store.clock
            store.clients.clear()
            store.advisors.clear()
            store.risk_questionnaires.clear()
            store.model_portfolios.clear()
            store.accounts.clear()
            store.securities.clear()
            store.correlation_links.clear()
            store.positions.clear()
            store.lots.clear()
            store.trades.clear()
            store.wash_sale_events.clear()
            store.harvest_opportunities.clear()
            store.rebalance_runs.clear()
            store.dividend_events.clear()
            store.forms_1099b.clear()
        return jsonify({"ok": True}), 200

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Not Found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_INVALID_STATE", "Method Not Allowed", 409)

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        return error_response("ERR_INVALID_STATE", exc.description or "HTTP error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INVALID_STATE", str(exc) or "Server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=HOST, port=PORT, threaded=True)
