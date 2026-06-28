"""Entry point: error handlers + route registration."""
import os

from flask import Flask

import errors
from response import error_response
from routes.clients import bp as clients_bp
from routes.contracts import bp as contracts_bp
from routes.proposals import bp as proposals_bp
from routes.inventory import bp as inventory_bp
from routes.crews import bp as crews_bp
from routes.work_orders import bp as work_orders_bp
from routes.visits import bp as visits_bp
from routes.storage import bp as storage_bp
from routes.damage import bp as damage_bp
from routes.restock import bp as restock_bp
from routes.renewal import bp as renewal_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(proposals_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(crews_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(damage_bp)
    app.register_blueprint(restock_bp)
    app.register_blueprint(renewal_bp)
    app.register_blueprint(clock_bp)

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
        return error_response(errors.ERR_INVALID_REQUEST, "Invalid request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False)
