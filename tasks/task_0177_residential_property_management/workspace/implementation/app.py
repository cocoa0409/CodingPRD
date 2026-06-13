"""Residential Property Management API — Flask entry point.

In-memory only. The store starts EMPTY on every boot; nothing is seeded.
The per-test-server harness relaunches start.sh (a fresh process) before each
test, which wipes all state.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

# Route blueprints
from routes.owners import bp as owners_bp
from routes.properties import bp as properties_bp
from routes.units import bp as units_bp
from routes.applicants import bp as applicants_bp
from routes.leases import bp as leases_bp
from routes.rent_charges import bp as rent_charges_bp
from routes.payments import bp as payments_bp
from routes.security_deposits import bp as security_deposits_bp
from routes.work_orders import bp as work_orders_bp
from routes.evictions import bp as evictions_bp
from routes.owner_statements import bp as owner_statements_bp
from routes.turnovers import bp as turnovers_bp
from routes.tenants import bp as tenants_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(owners_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(applicants_bp)
    app.register_blueprint(leases_bp)
    app.register_blueprint(rent_charges_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(security_deposits_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(evictions_bp)
    app.register_blueprint(owner_statements_bp)
    app.register_blueprint(turnovers_bp)
    app.register_blueprint(tenants_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request", 422)
        return error_response("ERR_INVALID_REQUEST", e.description or "Error", e.code or 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)

    @app.after_request
    def _close_connection(response):
        # Transport hygiene only: the per-test-server harness reuses a pooled
        # keep-alive client socket across the threaded Werkzeug dev server's
        # connection teardown, which can intermittently surface as a
        # BadStatusLine / ConnectionError race. Forcing Connection: close
        # prevents socket reuse. No endpoint, field, status code, error_id,
        # state transition, or calculation is affected.
        response.headers["Connection"] = "close"
        return response

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
