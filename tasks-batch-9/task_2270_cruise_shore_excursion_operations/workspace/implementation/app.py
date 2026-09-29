"""Cruise shore-excursion operations API. Boots empty on every invocation."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import bookings, claims, clock, departures, excursions, guests, incidents
from routes import operators, port_calls, ports, statements

BLUEPRINTS = (
    ports.bp,
    operators.bp,
    port_calls.bp,
    excursions.bp,
    departures.bp,
    guests.bp,
    bookings.bp,
    incidents.bp,
    claims.bp,
    statements.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_VALIDATION", "the requested route does not exist", 404)
        if exc.code == 405:
            return error_response("ERR_VALIDATION", "the method is not allowed on this route", 405)
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "the request could not be parsed", 400)
        return error_response("ERR_VALIDATION", exc.description or "request failed", exc.code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_VALIDATION", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
