"""Seafood Wholesale & Dockside Purchase API — Flask entry point.

In-memory only: all state lives in db.store (module-level dicts), empty at
boot. The evaluator contract is `bash start.sh` from this directory; the
server listens on 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import store
from errors import ApiError, ERR_INVALID_REQUEST
from response import err
from routes.config import bp as config_bp
from routes.quotes import bp as quotes_bp
from routes.tickets import bp as tickets_bp
from routes.lots import bp as lots_bp
from routes.orders import bp as orders_bp
from routes.shipments import bp as shipments_bp
from routes.compliance import bp as compliance_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize request handling: cascades span many records and must be
    # atomic with respect to concurrent requests on the threaded dev server.
    @app.before_request
    def _acquire_store():
        store.lock.acquire()

    @app.teardown_request
    def _release_store(exc):
        store.lock.release()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return err(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return err(ERR_INVALID_REQUEST, 400, "Unknown path")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return err(ERR_INVALID_REQUEST, 400, "Method not allowed")

    @app.errorhandler(Exception)
    def _internal(e):
        return err("ERR_INTERNAL", 500, "Internal server error: %s" % e)

    for bp in (
        config_bp,
        quotes_bp,
        tickets_bp,
        lots_bp,
        orders_bp,
        shipments_bp,
        compliance_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
