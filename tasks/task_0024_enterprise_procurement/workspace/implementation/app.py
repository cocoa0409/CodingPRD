"""Flask entry point for the enterprise procurement API.

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

    # Single-process serialization: PRD §2.9 requires that every concurrent
    # operation pair (approver race, award race, payment race, signature race,
    # budget commitment race) is resolved with a deterministic loser. The
    # simplest correct implementation is to acquire the global db lock for the
    # entire request lifecycle.
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
    from routes.system import bp as system_bp
    from routes.budget_accounts import bp as ba_bp
    from routes.suppliers import bp as suppliers_bp
    from routes.requirements import bp as req_bp
    from routes.quotes import bp as quotes_bp
    from routes.purchase_orders import bp as po_bp
    from routes.approval_steps import bp as steps_bp
    from routes.contracts import bp as contracts_bp
    from routes.clause_templates import bp as ct_bp
    from routes.receipts import bp as receipts_bp
    from routes.invoices import bp as invoices_bp
    from routes.payments import bp as payments_bp
    from routes.audit_log import bp as audit_bp

    for bp in (
        system_bp,
        ba_bp,
        suppliers_bp,
        req_bp,
        quotes_bp,
        po_bp,
        steps_bp,
        contracts_bp,
        ct_bp,
        receipts_bp,
        invoices_bp,
        payments_bp,
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
        body = error_response("ERR_VALIDATION", "Method not allowed.")
        return jsonify(body), 405

    @app.errorhandler(400)
    def _bad_request(exc):
        body = error_response("ERR_VALIDATION", str(getattr(exc, "description", "Bad request.")))
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _unhandled(exc):
        body = error_response("ERR_VALIDATION", f"Server error: {exc}")
        return jsonify(body), 500

    @app.get("/healthz")
    def _health():
        return {"status": "ok"}, 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
