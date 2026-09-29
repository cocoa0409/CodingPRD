"""Title agency oversight, closing protection and escrow compliance API.

Flask application factory and request lifecycle.  All state lives in memory in
`db.store` and is created exclusively through the endpoints below: the process
starts with every table empty and nothing seeded.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db
import response
import tx
from errors import ApiError
from routes import agencies, claims, clock, cpl, escrow, policy_files, remittance, state_programs

BLUEPRINTS = (
    agencies.bp,
    state_programs.bp,
    cpl.bp,
    policy_files.bp,
    remittance.bp,
    escrow.bp,
    claims.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _open_transaction():
        # One request at a time: every mutation is a single atomic step.
        db.request_lock.acquire()
        g.lock_held = True
        tx.begin()

    @app.teardown_request
    def _close_transaction(exc):
        if getattr(g, "lock_held", False):
            g.lock_held = False
            try:
                db.request_lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        tx.rollback()
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        tx.rollback()
        return response.error(
            "ERR_INVALID_REQUEST", err.description or "Request could not be handled.",
            err.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(err):
        tx.rollback()
        return response.error("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
