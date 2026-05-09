"""Flask entry point for the pharma e-commerce API.

Listens on the PORT env var (default 10000), bound to 0.0.0.0.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify

from db import db
from errors import ApiError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Serialize all request handling to enforce the PRD-required
    # state-machine serialization guarantees on race-prone endpoints
    # (PRD §3.5 pay/cancel race, §3.6 review-open race, §3.2 shelve race,
    # §3.7 dispatch idempotency, etc.). The benchmark uses a single
    # Flask process; an RLock on the global db is sufficient.
    @app.before_request
    def _acquire_db_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_db_lock(_exc):
        try:
            db.lock.release()
        except RuntimeError:
            # before_request never ran (e.g. routing 404 before our hook); ignore.
            pass

    # Register blueprints
    from routes.platforms import bp as platforms_bp
    from routes.drugs import bp as drugs_bp
    from routes.vendors import bp as vendors_bp
    from routes.pharmacists import bp as pharmacists_bp
    from routes.customers import bp as customers_bp
    from routes.denylist import bp as denylist_bp
    from routes.rules import bp as rules_bp
    from routes.prescriptions import bp as prescriptions_bp
    from routes.orders import bp as orders_bp
    from routes.reviews import bp as reviews_bp
    from routes.shipments import bp as shipments_bp
    from routes.adverse_reactions import bp as adr_bp
    from routes.audit_events import bp as audit_bp

    for bp in (
        platforms_bp,
        drugs_bp,
        vendors_bp,
        pharmacists_bp,
        customers_bp,
        denylist_bp,
        rules_bp,
        prescriptions_bp,
        orders_bp,
        reviews_bp,
        shipments_bp,
        adr_bp,
        audit_bp,
    ):
        app.register_blueprint(bp)

    # ----- Error handlers -----

    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        body = error_response(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        body = error_response("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        body = error_response("ERR_INVALID_REQUEST", "Method not allowed.")
        return jsonify(body), 405

    @app.errorhandler(400)
    def _bad_request(exc):
        body = error_response("ERR_INVALID_REQUEST", str(getattr(exc, "description", "Bad request.")))
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _unhandled(exc):
        # In production an unhandled exception would be logged; here, surface
        # a generic 500 with a stable error id so tests can detect failure.
        body = error_response("ERR_INVALID_REQUEST", f"Server error: {exc}")
        return jsonify(body), 500

    # ----- Health -----

    @app.get("/healthz")
    def _health():
        return {"status": "ok"}, 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
