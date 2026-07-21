"""Rebate & Incentive-Program Administration API.

Entry point: registers blueprints and the error handlers. The in-memory store
starts EMPTY on every boot - nothing is seeded.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import response as resp
from errors import ApiError
from routes import cards, claimants, claims, fraud_cases, ledger, offers, payouts, programs


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    # One request at a time: every mutation (and its cascade) is applied
    # atomically, which is what PRD §2.9 requires of the cascades.
    request_lock = threading.RLock()

    @app.before_request
    def _acquire():
        request_lock.acquire()

    @app.teardown_request
    def _release(exc=None):
        try:
            request_lock.release()
        except RuntimeError:
            pass

    app.register_blueprint(programs.bp)
    app.register_blueprint(offers.bp)
    app.register_blueprint(claimants.bp)
    app.register_blueprint(claims.bp)
    app.register_blueprint(payouts.bp)
    app.register_blueprint(cards.bp)
    app.register_blueprint(ledger.bp)
    app.register_blueprint(fraud_cases.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return resp.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return resp.error_response("ERR_VALIDATION", "Resource not found.", 404)
        if exc.code == 405:
            return resp.error_response("ERR_VALIDATION", "Method not allowed.", 405)
        return resp.error_response("ERR_VALIDATION", exc.description or "Bad request", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        return resp.error_response("ERR_VALIDATION", "Internal error: %s" % exc, 500)

    db.reset()
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
