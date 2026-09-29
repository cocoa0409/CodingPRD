"""Governance Records API — School Board Policy & Governance Management."""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import resp
import store
from errors import ApiError

import routes_board
import routes_policy
import routes_meeting
import routes_agenda
import routes_waiver
import routes_ops


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_board.bp)
    app.register_blueprint(routes_policy.bp)
    app.register_blueprint(routes_meeting.bp)
    app.register_blueprint(routes_agenda.bp)
    app.register_blueprint(routes_waiver.bp)
    app.register_blueprint(routes_ops.bp)

    # Requests are handled one at a time so that read-modify-write sequences
    # (optimistic concurrency, counter recomputation, cascades) stay atomic,
    # while the server still accepts many simultaneous connections.
    request_lock = threading.Lock()

    @app.before_request
    def _reset_request_state():
        request_lock.acquire()
        g._holds_request_lock = True
        store.reset_request_state()

    @app.teardown_request
    def _release_request_lock(exc=None):
        if g.pop("_holds_request_lock", False):
            try:
                request_lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return resp.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return resp.error("ERR_INVALID_REQUEST",
                              "The requested resource does not exist.", 404)
        if exc.code == 405:
            return resp.error("ERR_INVALID_REQUEST",
                              "The HTTP method is not allowed here.", 405)
        if exc.code == 400:
            return resp.error("ERR_INVALID_REQUEST",
                              "The request body could not be parsed.", 400)
        return resp.error("ERR_INVALID_REQUEST",
                          exc.description or "Request failed.", exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return resp.error("ERR_INVALID_REQUEST", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
