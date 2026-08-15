"""Touring Theatrical Management API — Flask entry point.

Storage is in-memory only (module-level dicts in db.py), empty on every boot.
No entity is seeded, preloaded, or hardcoded at startup.
"""

import os

from flask import Flask

import response
from errors import ApiError, err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from routes import (tours, venues, stops, tech_checks, performances,
                    settlements, cast, tracks, coverages, injuries, per_diems,
                    crew_calls, clock)


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return response.error(e)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error(err(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return response.error(err(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return response.error(err(ERR_INVALID_REQUEST, 400, str(e)))

    for bp in (tours.bp, venues.bp, stops.bp, tech_checks.bp, performances.bp,
               settlements.bp, cast.bp, tracks.bp, coverages.bp, injuries.bp,
               per_diems.bp, crew_calls.bp, clock.bp):
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
