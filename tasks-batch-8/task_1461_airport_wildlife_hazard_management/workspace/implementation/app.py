"""Airport Wildlife Hazard API — Flask entry point.

In-memory store, logical clock defaulting to 2026-08-01T00:00:00Z.
Every request first evaluates pending system-event transitions against the
logical clock (permit activation/expiry, advisory expiry, closure activation,
training expiry, rolling strike-window rollover).
"""
import os
import threading

from flask import Flask

import errors as E
from db import store
from services import tick
from util import error_response, make_meta
from flask import jsonify

from routes.airports import bp as airports_bp
from routes.species import bp as species_bp
from routes.people import bp as people_bp
from routes.strikes import bp as strikes_bp
from routes.carcasses import bp as carcasses_bp
from routes.habitat import bp as habitat_bp
from routes.dispersals import bp as dispersals_bp
from routes.permits import bp as permits_bp
from routes.advisories import bp as advisories_bp
from routes.closures import bp as closures_bp
from routes.plans import bp as plans_bp
from routes.training import bp as training_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (airports_bp, species_bp, people_bp, strikes_bp, carcasses_bp,
               habitat_bp, dispersals_bp, permits_bp, advisories_bp, closures_bp,
               plans_bp, training_bp):
        app.register_blueprint(bp)

    @app.before_request
    def _evaluate_system_events():
        with store.lock:
            tick()

    @app.errorhandler(E.ApiError)
    def _api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(E.not_found("resource"))

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(E.not_found("resource"))

    @app.errorhandler(Exception)
    def _unexpected(e):
        if isinstance(e, E.ApiError):
            return error_response(e)
        app.logger.exception("unexpected error")
        return error_response(E.ApiError(E.ERR_INVALID_REQUEST, f"internal error: {e}", 400))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
