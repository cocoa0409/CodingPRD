"""Flask entry point for the Sporting Goods Retail API.

Wires every blueprint, registers the standard error envelope handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000). The in-memory
store starts EMPTY on every boot — no seeding, no preloaded entities.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.catalog import bp as catalog_bp
from routes.inventory import bp as inventory_bp
from routes.orders import bp as orders_bp
from routes.service_tickets import bp as service_tickets_bp
from routes.fishing_licenses import bp as fishing_licenses_bp
from routes.markdowns import bp as markdowns_bp
from routes.price_match_claims import bp as price_match_claims_bp
from routes.team_orders import bp as team_orders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(service_tickets_bp)
    app.register_blueprint(fishing_licenses_bp)
    app.register_blueprint(markdowns_bp)
    app.register_blueprint(price_match_claims_bp)
    app.register_blueprint(team_orders_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route / unresolved path -> standard ERR_NOT_FOUND envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        # Method not allowed on a known path -> not found in the envelope vocabulary.
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 422)

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
