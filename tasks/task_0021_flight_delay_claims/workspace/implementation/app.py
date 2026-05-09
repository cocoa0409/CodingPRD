"""Flask entry point for the Flight Delay Claims API.

Listens on the PORT env var (default 10000), bound to 0.0.0.0.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify

from db import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize all request handling to enforce state-machine ordering on
    # race-prone endpoints (PRD §2.9). The benchmark uses a single Flask
    # process; an RLock on the global db is sufficient.
    @app.before_request
    def _acquire_db_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_db_lock(_exc):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    # Register blueprints
    from routes.insurers import bp as insurers_bp
    from routes.policies import bp as policies_bp
    from routes.tickets import bp as tickets_bp
    from routes.flights import bp as flights_bp
    from routes.manual_review import bp as manual_review_bp
    from routes.claims import bp as claims_bp
    from routes.payout_batches import bp as batches_bp
    from routes.audit_outbox import bp as audit_outbox_bp

    for bp in (
        insurers_bp,
        policies_bp,
        tickets_bp,
        flights_bp,
        manual_review_bp,
        claims_bp,
        batches_bp,
        audit_outbox_bp,
    ):
        app.register_blueprint(bp)

    # ----- Error handlers -----

    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        body = error_response(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        body = error_response(ERR_NOT_FOUND, "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        body = error_response(ERR_NOT_FOUND, "Method not allowed.")
        return jsonify(body), 404

    @app.errorhandler(400)
    def _bad_request(_exc):
        body = error_response(ERR_INVALID_REQUEST, "Bad request.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        # Fail fast for unexpected exceptions but with a consistent envelope.
        body = error_response("ERR_INVALID_REQUEST", f"Unhandled error: {exc!r}")
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=False)
