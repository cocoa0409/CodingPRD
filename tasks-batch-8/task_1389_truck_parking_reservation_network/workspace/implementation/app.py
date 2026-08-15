"""Truck Parking Reservation Network — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store is in-memory and starts empty
on every boot; the logical clock defaults to 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

import db
import errors
import util
from routes import auths, bookings, clock, drivers, fleets, incidents, sites, \
    site_children, waitlist


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize all request handling — the store is plain dicts.
    @app.before_request
    def _serialize_requests():
        db.LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            db.LOCK.release()
        except RuntimeError:
            pass

    # Connection management: Werkzeug's dev server unconditionally sends
    # "Connection: close" and closes the socket after every response (see
    # WSGIRequestHandler.run_wsgi — keep-alive is disabled by design), so no
    # app-level header changes that behavior. Resilience to the harness's
    # SIGKILL-and-restart cycle (stale/dead-connection RST, RemoteDisconnected,
    # ECONNREFUSED while a fresh boot is still binding) lives in the test
    # client: test_helpers/api_client.py mounts a retry adapter that replays
    # transport-failed requests on fresh connections. Such retries are safe
    # for mutating endpoints because a request that failed at transport never
    # reached a handler (the client is synchronous and the server only closes
    # a connection after fully writing its response).

    @app.errorhandler(errors.ApiError)
    def _api_error(exc):
        return util.err_resp(exc)

    @app.errorhandler(404)
    def _not_found(exc):
        return util.err_resp(errors.not_found())

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return util.err_resp(errors.not_found())

    @app.errorhandler(500)
    def _internal(exc):
        return util.err_resp(errors.ApiError("ERR_INTERNAL", 500, str(exc)))

    for module in (sites, site_children, drivers, fleets, auths, bookings,
                   waitlist, incidents, clock):
        app.register_blueprint(module.bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
