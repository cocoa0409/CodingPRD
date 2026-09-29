"""Gift-card fraud and balance-protection API (Flask entry point).

The in-memory store starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded. Tests build all state through the declared
endpoints. The only boot-time record is the singleton risk-policy register
of PRD 2.5, which the API exposes as configuration rather than as an entity.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.alerts import bp as alerts_bp
from routes.bulk import bp as bulk_bp
from routes.claims import bp as claims_bp
from routes.config import bp as config_bp
from routes.gift_cards import bp as gift_cards_bp
from routes.issuance import bp as issuance_bp
from routes.ledger import bp as ledger_bp
from routes.liability import bp as liability_bp
from routes.listings import bp as listings_bp
from routes.stores import bp as stores_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (config_bp, stores_bp, gift_cards_bp, issuance_bp, bulk_bp,
                      alerts_bp, claims_bp, listings_bp, liability_bp, ledger_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error("ERR_METHOD_NOT_ALLOWED",
                              "The HTTP method is not allowed for this resource.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST",
                                  "The request body could not be parsed.", 400)
        return response.error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
