"""Flask entry point for the Garbage Sorting Points API.

Listens on the PORT env var (default 10000), bound to 0.0.0.0.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify

from flask import request

from db import db
from errors import (
    ApiError,
    ERR_AUTH_REQUIRED,
    ERR_NOT_FOUND,
    ERR_UNKNOWN_ROLE,
    ERR_VALIDATION,
    raise_api_error,
)
from response import error_response


_VALID_ROLES = {"SystemOperator", "CommunityAdmin", "AppealReviewer", "Resident"}


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # PRD §2.10: auth headers are checked FIRST — before path-id resolution.
    # Unknown paths must therefore yield ERR_AUTH_REQUIRED / ERR_UNKNOWN_ROLE
    # before Flask's 404. Exempt only the test-only /_test/reset hook.
    @app.before_request
    def _global_auth_check():
        if request.path == "/_test/reset":
            return None
        user_id = request.headers.get("X-User-ID", "")
        user_role = request.headers.get("X-User-Role", "")
        if not user_id or not user_role:
            body = error_response(
                ERR_AUTH_REQUIRED,
                "X-User-ID and X-User-Role headers are required.",
            )
            return jsonify(body), 401
        if user_role not in _VALID_ROLES:
            body = error_response(
                ERR_UNKNOWN_ROLE,
                f"Unknown role: {user_role}",
            )
            return jsonify(body), 401
        return None

    # Serialize all request handling on a single RLock so race-prone
    # transitions (redemption confirm, ranking close, rule activation,
    # appeal) get first-writer-wins semantics. Tests assert this.
    @app.before_request
    def _acquire_db_lock():
        db.lock.acquire()

    @app.teardown_request
    def _release_db_lock(_exc):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    # ------ Blueprints ------
    from routes.communities import bp as communities_bp
    from routes.households import bp as households_bp
    from routes.residents import bp as residents_bp
    from routes.point_rules import bp as point_rules_bp
    from routes.disposals import bp as disposals_bp
    from routes.points_transactions import bp as points_tx_bp
    from routes.mall_items import bp as mall_items_bp
    from routes.redemption_orders import bp as redemption_bp
    from routes.violations import bp as violations_bp
    from routes.ranking_periods import bp as ranking_bp
    from routes.audit_logs import bp as audit_bp
    from routes.test_driving import bp as test_driving_bp

    for bp in (
        communities_bp,
        households_bp,
        residents_bp,
        point_rules_bp,
        disposals_bp,
        points_tx_bp,
        mall_items_bp,
        redemption_bp,
        violations_bp,
        ranking_bp,
        audit_bp,
        test_driving_bp,
    ):
        app.register_blueprint(bp)

    # ------ Error handlers ------
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
        body = error_response(ERR_VALIDATION, "Bad request.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        # Fail fast for unexpected exceptions, but keep envelope.
        body = error_response(ERR_VALIDATION, f"Unhandled error: {exc!r}")
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=False)
