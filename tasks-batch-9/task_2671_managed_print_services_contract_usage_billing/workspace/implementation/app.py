"""Managed Print Services contract usage & billing API.

Every byte of state lives in the in-memory `store.db` singleton, so each fresh
process (one `start.sh` invocation) starts completely empty.  Nothing is seeded:
tests build all entity state through the declared endpoints.
"""
import os

from flask import Flask

from envelope import error
from errors import ApiError
from routes import (billing, clock, consumables, contracts, devices, meters,
                    removals, reviews, sites, technicians, tickets)

BLUEPRINTS = (
    contracts.bp,
    sites.bp,
    devices.bp,
    technicians.bp,
    meters.bp,
    billing.bp,
    consumables.bp,
    tickets.bp,
    reviews.bp,
    removals.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_INVALID_REQUEST", "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error("ERR_INVALID_REQUEST",
                     "The HTTP method is not allowed for this route.", 405)

    @app.errorhandler(415)
    def _unsupported_media(exc):
        return error("ERR_INVALID_REQUEST", "Request body must be JSON.", 422)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error("ERR_INVALID_REQUEST", "The request could not be parsed.", 422)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        return error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
