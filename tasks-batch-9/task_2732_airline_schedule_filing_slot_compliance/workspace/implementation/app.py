"""Airline schedule filing and slot compliance API. Flat topology, no path prefix."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import envelope_error
from routes.aircraft import bp as aircraft_bp
from routes.filings import bp as filings_bp
from routes.flight_legs import bp as flight_legs_bp
from routes.notifications import bp as notifications_bp
from routes.reference import bp as reference_bp
from routes.schedule_versions import bp as schedule_versions_bp
from routes.seasons import bp as seasons_bp
from routes.slots import bp as slots_bp
from routes.transactions import bp as transactions_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (
        reference_bp,
        seasons_bp,
        aircraft_bp,
        schedule_versions_bp,
        flight_legs_bp,
        slots_bp,
        transactions_bp,
        filings_bp,
        notifications_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return envelope_error("ERR_NOT_FOUND", "No such route.", 404)
        if exc.code == 405:
            return envelope_error(
                "ERR_METHOD_NOT_ALLOWED", "That method is not allowed on this route.", 405
            )
        if exc.code == 400:
            return envelope_error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return envelope_error("ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return envelope_error("ERR_INVALID_REQUEST", "Unexpected server condition: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
