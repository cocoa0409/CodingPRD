"""Flask app entry point: error handlers + route registration."""

import os
from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.operations import bp as operations_bp
from routes.baselines import bp as baselines_bp
from routes.insurance import bp as insurance_bp
from routes.plans import bp as plans_bp
from routes.targets_ticks import bp as targets_ticks_bp
from routes.recommendations import bp as recommendations_bp
from routes.positions_margin import bp as positions_margin_bp
from routes.buyers_contracts import bp as buyers_contracts_bp
from routes.tickets import bp as tickets_bp
from routes.storage import bp as storage_bp
from routes.agreements import bp as agreements_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback

        traceback.print_exc()
        return error_response("ERR_INTERNAL", f"Internal error: {err}", 500)

    app.register_blueprint(operations_bp)
    app.register_blueprint(baselines_bp)
    app.register_blueprint(insurance_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(targets_ticks_bp)
    app.register_blueprint(recommendations_bp)
    app.register_blueprint(positions_margin_bp)
    app.register_blueprint(buyers_contracts_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(storage_bp)
    app.register_blueprint(agreements_bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
