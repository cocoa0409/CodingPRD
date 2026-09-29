"""Retransmission consent negotiation and carriage settlement API.

In-memory only: every dict in store.DB starts empty on boot and no entity is
ever seeded. Tests build all state through the declared endpoints.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes_agreements
import routes_elections
import routes_negotiations
import routes_reports
import routes_setup
from envelope import error_response
from errors import ApiError
from store import lock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.register_blueprint(routes_setup.bp)
    app.register_blueprint(routes_elections.bp)
    app.register_blueprint(routes_reports.bp)
    app.register_blueprint(routes_negotiations.bp)
    app.register_blueprint(routes_agreements.bp)

    @app.before_request
    def _serialize_request():
        # One writer at a time: every cascade in this system spans several rows.
        lock.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release_request(_exc=None):
        if g.pop("_store_locked", False):
            lock.release()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.http_status, error.message)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return error_response("ERR_INVALID_REQUEST", 404, "Resource not found.")
        if error.code == 405:
            return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed.")
        if error.code == 415:
            return error_response("ERR_INVALID_REQUEST", 400, "Request body must be JSON.")
        return error_response("ERR_INVALID_REQUEST", error.code or 400,
                              error.description or "Invalid request.")

    @app.errorhandler(Exception)
    def _unhandled(error):
        return error_response("ERR_INVALID_REQUEST", 500, str(error))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
