"""P2P Team Fundraising API — Flask entry point.

Storage is in-memory only and starts EMPTY on every boot; no entity is
seeded or preloaded at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    campaigns,
    clock,
    donations,
    donors,
    events,
    incentives,
    match_pools,
    organizations,
    participants,
    payouts,
    receipts,
    registrations,
    teams,
)

BLUEPRINTS = (
    organizations.bp,
    campaigns.bp,
    events.bp,
    teams.bp,
    participants.bp,
    registrations.bp,
    donors.bp,
    donations.bp,
    match_pools.bp,
    incentives.bp,
    receipts.bp,
    payouts.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The requested route does not exist.", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
