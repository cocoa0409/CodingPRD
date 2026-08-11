"""Entry point for the Fiscal Sponsorship Administration API.

Flask app: registers blueprints, envelope-shaped error handlers, and binds
0.0.0.0:$PORT (default 10000). The store is in-memory only and starts empty on
every boot — nothing is seeded.
"""

import os
import threading

from flask import Flask, g

from envelope import err_response
from errors import ApiError
from routes import (
    agreements,
    applications,
    clock,
    compliance,
    disbursements,
    donations,
    engagements,
    exits,
    funds,
    projects,
)

# Serialize all requests: keeps in-memory mutations race-free under the
# threaded dev server.
_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        applications,
        projects,
        agreements,
        donations,
        disbursements,
        engagements,
        compliance,
        exits,
        funds,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.before_request
    def _acquire():
        _REQUEST_LOCK.acquire()

    @app.teardown_request
    def _release(exc=None):
        if _REQUEST_LOCK._is_owned():
            _REQUEST_LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return err_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _not_found(err):
        return err_response("ERR_VALIDATION", 404, "route not found")

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return err_response("ERR_VALIDATION", 405, "method not allowed")

    @app.errorhandler(Exception)
    def _unhandled(err):
        return err_response("ERR_VALIDATION", 500, "internal error: %s" % err)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
