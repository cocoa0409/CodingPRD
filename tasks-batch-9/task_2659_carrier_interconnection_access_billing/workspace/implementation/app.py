"""Carrier Interconnection & Access Billing service.

Flask application factory and blueprint wiring. All state lives in memory and
starts empty on every boot (see store.py); nothing is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import (agreements, augments, carriers, clock, disputes, factors,
                    invoices, ledger, recon, tariffs, trunks, usage)

API_PREFIX = "/interconnection"

BLUEPRINTS = (
    carriers.bp,
    agreements.bp,
    trunks.bp,
    augments.bp,
    tariffs.bp,
    factors.bp,
    usage.bp,
    invoices.bp,
    disputes.bp,
    recon.bp,
    ledger.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
    # PRD 4: the clock capability is not mounted under /interconnection.
    app.register_blueprint(clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "resource not found", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "method not allowed", 405)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "invalid request",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
