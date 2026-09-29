"""Wound Ostomy Continence Nurse Consult Service — application entry point.

All state lives in process memory (see core.Database); nothing is persisted and
nothing is seeded, so a fresh boot always starts from an empty world.  The
harness reboots this process before every individual test.
"""

import os
from decimal import Decimal

from flask import Flask, request
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

from core import ApiError, CLOCK, ROLE_SYSOP, F, authorize, error_body, ok, parse_input
import routes_clinical
import routes_consult
import routes_formulary
import routes_org
import routes_rental
import routes_survey


class ServiceJSON(DefaultJSONProvider):
    """Decimal is rendered as a JSON number, never as a string."""

    sort_keys = False

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            as_int = int(obj)
            return as_int if Decimal(as_int) == obj else float(obj)
        return DefaultJSONProvider.default(obj)


def create_app():
    app = Flask(__name__)
    app.json = ServiceJSON(app)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_org.bp)
    app.register_blueprint(routes_consult.bp)
    app.register_blueprint(routes_clinical.bp)
    app.register_blueprint(routes_survey.bp)
    app.register_blueprint(routes_rental.bp)
    app.register_blueprint(routes_formulary.bp)

    # -----------------------------------------------------------------------
    # Test-driving surface: the logical clock every deadline rule reads.
    # -----------------------------------------------------------------------
    @app.post("/_clock/set_current_utc")
    def set_clock():
        authorize(ROLE_SYSOP)
        body = parse_input([F("to_iso8601", "datetime", required=True)])
        current = CLOCK.set(body["to_iso8601"])
        return ok({"current_utc": current})

    # -----------------------------------------------------------------------
    # Error handling — every failure leaves through the same envelope.
    # -----------------------------------------------------------------------
    @app.errorhandler(ApiError)
    def on_api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(400)
    def on_bad_request(exc):
        return error_body("ERR_INVALID_REQUEST",
                          "Request payload or query string is invalid."), 400

    @app.errorhandler(404)
    def on_not_found(exc):
        return error_body("ERR_INVALID_REQUEST",
                          "No route matches %s %s." % (request.method, request.path)), 404

    @app.errorhandler(405)
    def on_method_not_allowed(exc):
        return error_body("ERR_INVALID_REQUEST",
                          "Method %s is not allowed on %s." % (request.method,
                                                               request.path)), 405

    @app.errorhandler(415)
    def on_unsupported_media(exc):
        return error_body("ERR_INVALID_REQUEST",
                          "Request body must be JSON."), 400

    @app.errorhandler(Exception)
    def on_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_body(exc.error_id, exc.message), exc.http_status
        if isinstance(exc, HTTPException):
            status = exc.code or 500
            return error_body("ERR_INVALID_REQUEST",
                              exc.description or "Request could not be served."), status
        app.logger.exception("unhandled error")
        return error_body("ERR_INVALID_REQUEST", "Unexpected server error."), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
