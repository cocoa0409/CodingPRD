"""Hail-catastrophe paintless dent repair operations service.

Storage is in-memory only: every collection starts empty on every boot and no entity
is ever seeded. Clients create everything through the declared endpoints.
"""

import os
import threading

from flask import Flask, g

from errors import ApiError
from response import error_response
from routes import (
    clock_admin,
    crew_deployments,
    damage_lines,
    facilities,
    housing_units,
    insurers,
    permits,
    quality_inspections,
    rate_agreements,
    storm_events,
    supplements,
    technicians,
    vehicles,
    work_tickets,
)

BLUEPRINTS = (
    storm_events.bp,
    facilities.bp,
    permits.bp,
    housing_units.bp,
    technicians.bp,
    crew_deployments.bp,
    insurers.bp,
    rate_agreements.bp,
    vehicles.bp,
    damage_lines.bp,
    work_tickets.bp,
    supplements.bp,
    quality_inspections.bp,
    clock_admin.bp,
)

# Every request mutates or reads the same in-memory store, and several handlers run
# multi-step cascades. One global lock keeps a cascade atomic against a concurrent read.
_REQUEST_LOCK = threading.Lock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _acquire():
        _REQUEST_LOCK.acquire()
        g.store_locked = True

    @app.teardown_request
    def _release(_exc=None):
        # Only the thread that actually acquired the lock may release it: a routing
        # failure never runs before_request, yet its teardown still fires.
        if getattr(g, "store_locked", False):
            g.store_locked = False
            try:
                _REQUEST_LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _not_found(_error):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        return error_response(
            "ERR_INVALID_REQUEST", "Method not allowed for this resource.", 405
        )

    @app.errorhandler(Exception)
    def _unhandled(error):
        if isinstance(error, ApiError):
            return error_response(error.error_id, error.message, error.http_status)
        return error_response("ERR_INVALID_REQUEST", "Malformed request: %s" % error, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
