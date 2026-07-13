"""Fleet Fuel Card & Telematics API — entry point.

State lives only in process memory (see db.py).  Nothing is seeded at startup:
every entity is created by callers through the declared endpoints, so a fresh
process always begins with a completely empty store.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.card_assignments import bp as card_assignments_bp
from routes.clock import bp as clock_bp
from routes.drivers import bp as drivers_bp
from routes.fleet_accounts import bp as fleet_accounts_bp
from routes.fraud_alerts import bp as fraud_alerts_bp
from routes.fuel_cards import bp as fuel_cards_bp
from routes.ifta_reports import bp as ifta_reports_bp
from routes.telematics_faults import bp as telematics_faults_bp
from routes.transactions import bp as transactions_bp
from routes.vehicles import bp as vehicles_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in (
        clock_bp,
        fleet_accounts_bp,
        vehicles_bp,
        drivers_bp,
        fuel_cards_bp,
        card_assignments_bp,
        transactions_bp,
        fraud_alerts_bp,
        telematics_faults_bp,
        ifta_reports_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_VALIDATION", "Unknown route.", 404)
        if exc.code == 405:
            return response.error("ERR_VALIDATION", "Method not allowed for this route.", 405)
        if exc.code in (400, 415):
            return response.error("ERR_VALIDATION", "Malformed request.", 400)
        return response.error("ERR_VALIDATION", exc.description or "Request failed", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        app.logger.exception("unhandled error")
        return response.error("ERR_VALIDATION", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
