"""Flask entry point for the Title Insurance Escrow API.

Wires every blueprint, registers the standard error envelope handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000). The in-memory
store starts EMPTY on every boot — no seeding.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.agencies import bp as agencies_bp
from routes.plant_records import bp as plant_records_bp
from routes.orders import bp as orders_bp
from routes.title_searches import bp as title_searches_bp
from routes.commitments import bp as commitments_bp
from routes.exceptions_route import bp as exceptions_bp
from routes.policies import bp as policies_bp
from routes.endorsements import bp as endorsements_bp
from routes.deposits import bp as deposits_bp
from routes.disbursements import bp as disbursements_bp
from routes.remittances import bp as remittances_bp
from routes.claims import bp as claims_bp
from routes.curative_actions import bp as curative_actions_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(agencies_bp)
    app.register_blueprint(plant_records_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(title_searches_bp)
    app.register_blueprint(commitments_bp)
    app.register_blueprint(exceptions_bp)
    app.register_blueprint(policies_bp)
    app.register_blueprint(endorsements_bp)
    app.register_blueprint(deposits_bp)
    app.register_blueprint(disbursements_bp)
    app.register_blueprint(remittances_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(curative_actions_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route / unresolved path -> standard ERR_NOT_FOUND envelope.
        return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
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
