"""Rotational Molding Watercraft Plant API.

Storage is in-memory only: plain Python dicts held on the single `core.S`
store.  Nothing is seeded, preloaded or registered at startup, and nothing is
written to disk, so re-invoking start.sh wipes every byte of state.
"""
import os

from flask import Flask

import core
import r_clock
import r_cycles
import r_equip
import r_models
import r_orders
import r_party
import r_resin
import r_ship
import r_units
import r_warranty
from errors import ApiError

BLUEPRINTS = (
    r_models.bp,
    r_equip.bp,
    r_party.bp,
    r_resin.bp,
    r_orders.bp,
    r_cycles.bp,
    r_units.bp,
    r_ship.bp,
    r_warranty.bp,
    r_clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return core.respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return core.respond_error("ERR_RESOURCE_NOT_FOUND",
                                  "No such resource.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return core.respond_error("ERR_RESOURCE_NOT_FOUND",
                                  "Method not allowed on this path.", 404)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return core.respond_error("ERR_VALIDATION",
                                  "The request could not be parsed.", 422)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return core.respond_error(exc.error_id, exc.message, exc.http_status)
        # A broken ledger invariant is a server defect, not a client error, so it
        # is left to surface as a 500 rather than being disguised as a 422.
        if isinstance(exc, AssertionError):
            raise exc
        return core.respond_error("ERR_VALIDATION", str(exc) or "Request failed.",
                                  422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
