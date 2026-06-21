"""Crop Insurance (USDA RMA) Administration API — entry point.

Registers all routes, installs the error handler that renders the standard error
envelope, and runs the server in the foreground on 0.0.0.0:$PORT (default 10000).
In-memory store only; a fresh process boots with an empty store.
"""
import os

from flask import Flask

import response
from errors import ApiError

from routes.identity import bp as identity_bp
from routes.commodity_programs import bp as commodity_programs_bp
from routes.policies import bp as policies_bp
from routes.coverage_elections import bp as coverage_elections_bp
from routes.units import bp as units_bp
from routes.acreage_reports import bp as acreage_reports_bp
from routes.loss_claims import bp as loss_claims_bp
from routes.prevented_planting_claims import bp as pp_claims_bp
from routes.agent_commissions import bp as agent_commissions_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(identity_bp)
    app.register_blueprint(commodity_programs_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(coverage_elections_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(acreage_reports_bp)
    app.register_blueprint(loss_claims_bp)
    app.register_blueprint(pp_claims_bp)
    app.register_blueprint(agent_commissions_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return response.error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
