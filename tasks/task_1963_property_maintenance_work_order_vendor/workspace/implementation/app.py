"""Flask application entry point: error handlers, request serialization, and
blueprint registration.

Every request runs under a single process-wide lock so multi-step cascades
and optimistic-concurrency checks are atomic (PRD 2.9: side effects commit
atomically with the primary transition).
"""

import logging
import os

from flask import Flask

from db import store
from errors import ApiError
from response import error_response
import routes_admin
import routes_chargebacks
import routes_lines
import routes_master
import routes_purchase
import routes_work_orders


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    @app.before_request
    def _acquire_lock():
        store.lock.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        store.lock.release()

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(err):
        return error_response(
            ApiError("ERR_NOT_FOUND", 404, "The requested resource does not exist")
        )

    @app.errorhandler(405)
    def _handle_405(err):
        return error_response(
            ApiError("ERR_NOT_FOUND", 404, "The requested resource does not exist")
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_response(ApiError("ERR_VALIDATION", 400, f"Malformed request: {err}"))

    app.register_blueprint(routes_master.bp)
    app.register_blueprint(routes_work_orders.bp)
    app.register_blueprint(routes_lines.bp)
    app.register_blueprint(routes_purchase.bp)
    app.register_blueprint(routes_chargebacks.bp)
    app.register_blueprint(routes_admin.bp)
    return app


app = create_app()

if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
