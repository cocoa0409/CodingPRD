"""Flask entry point: error handlers, route registration, startup sweep."""

import os

from flask import Flask, jsonify

import db as _db
from errors import ApiError, err_invalid_request, err_not_found
from response import error_response
from services.sweep import run_clock_sweep

from routes.payers import bp as payers_bp
from routes.contracts import bp as contracts_bp
from routes.terms import bp as terms_bp
from routes.provisions import bp as provisions_bp
from routes.escalators import bp as escalators_bp
from routes.amendments import bp as amendments_bp
from routes.network_agreements import bp as network_agreements_bp
from routes.claims import bp as claims_bp
from routes.remittances import bp as remittances_bp
from routes.cases import bp as cases_bp
from routes.appeals import bp as appeals_bp
from routes.proposals import bp as proposals_bp
from routes.alerts import bp as alerts_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        payers_bp,
        contracts_bp,
        terms_bp,
        provisions_bp,
        escalators_bp,
        amendments_bp,
        network_agreements_bp,
        claims_bp,
        remittances_bp,
        cases_bp,
        appeals_bp,
        proposals_bp,
        alerts_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        import traceback
        traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", f"Unhandled error: {e}", 400)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()

# The clock sweep runs once at startup against the default clock (2026-08-01T00:00:00Z).
# The store starts empty, so this is a no-op on a fresh boot, but per PRD §2.4 the sweep
# is invoked here for contract fidelity.
with app.app_context():
    run_clock_sweep()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
