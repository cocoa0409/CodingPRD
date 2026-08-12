"""School Bus Contractor Operations API — Flask entry point."""
import os
import threading

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes import (
    assignments,
    buses,
    charter_trips,
    clock,
    contracts,
    credentials,
    districts,
    drivers,
    fuel,
    incidents,
    inspections,
    invoices,
    ridership,
    routes,
    service_days,
    training_events,
    work_orders,
)

_request_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock.bp,
        districts.bp,
        contracts.bp,
        routes.bp,
        drivers.bp,
        training_events.bp,
        credentials.bp,
        buses.bp,
        inspections.bp,
        work_orders.bp,
        service_days.bp,
        assignments.bp,
        charter_trips.bp,
        fuel.bp,
        invoices.bp,
        incidents.bp,
        ridership.bp,
    ):
        app.register_blueprint(bp)

    @app.before_request
    def _acquire_lock():
        _request_lock.acquire()

    @app.teardown_request
    def _release_lock(exc):
        _request_lock.release()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def _internal(err):
        return error_response("ERR_INTERNAL", 500, "Internal server error: %s" % err)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
