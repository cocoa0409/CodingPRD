"""Dermatology Practice API — Flask entry point.

In-memory only. State starts EMPTY on every boot and is wiped on restart.
No entity is seeded, preloaded, or hardcoded at startup.
"""
import os

from flask import Flask, request

import clock
import db
import errors
import middleware
import response

from routes.system import bp as system_bp
from routes.providers import bp as providers_bp
from routes.rooms import bp as rooms_bp
from routes.patients import bp as patients_bp
from routes.encounters import bp as encounters_bp
from routes.skin_exam_photos import bp as photos_bp
from routes.biopsies import bp as biopsies_bp
from routes.procedure_bookings import bp as bookings_bp
from routes.prior_authorizations import bp as pa_bp
from routes.cosmetic_memberships import bp as memberships_bp
from routes.cosmetic_treatments import bp as treatments_bp
from routes.charges import bp as charges_bp
from routes.recall_reminders import bp as recalls_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Fresh process => fresh, empty store + default clock.
    db.reset()
    clock.reset()

    @app.before_request
    def _auth():
        # Priority 1: auth context on every request (PRD 2.1).
        middleware.extract_auth()

    for bp in (
        system_bp, providers_bp, rooms_bp, patients_bp, encounters_bp,
        photos_bp, biopsies_bp, bookings_bp, pa_bp, memberships_bp,
        treatments_bp, charges_bp, recalls_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def _api_error(e):
        return response.error(e)

    @app.errorhandler(404)
    def _not_found(e):
        # Unknown route -> generic 404 in the standard envelope.
        return response.error(errors.ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return response.error(errors.ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))

    @app.errorhandler(Exception)
    def _unhandled(e):
        if isinstance(e, errors.ApiError):
            return response.error(e)
        return response.error(errors.ApiError("ERR_INTERNAL", 500, str(e)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
