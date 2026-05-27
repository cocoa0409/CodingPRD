"""Entry point for the 401(k) Retirement Plan API.

Boots cleanly from an empty in-memory store on every process start. The test
harness restarts this process before every pytest test, so all
test-prerequisite state must be constructed via the API surface.
"""

from __future__ import annotations

import os
import traceback

from flask import Flask, jsonify, request

from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response

from routes.plans import bp as plans_bp
from routes.participants import bp as participants_bp
from routes.contribution_periods import bp as contribution_periods_bp
from routes.loans import bp as loans_bp
from routes.hardships import bp as hardships_bp
from routes.rmd_distributions import bp as rmd_bp
from routes.vesting_events import bp as vesting_events_bp
from routes.system import bp as system_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Keep JSON keys in their natural order, not alphabetically sorted.
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(plans_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(contribution_periods_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(hardships_bp)
    app.register_blueprint(rmd_bp)
    app.register_blueprint(vesting_events_bp)
    app.register_blueprint(system_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response(ERR_NOT_FOUND, 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(_):
        return error_response(ERR_NOT_FOUND, 404, "Route not found")

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response(ERR_INVALID_REQUEST, 400, str(exc) or "Bad request")

    @app.errorhandler(Exception)
    def handle_generic(exc):
        # Defensive: never expose a raw stack trace, but ensure the envelope is right.
        traceback.print_exc()
        return error_response(ERR_INVALID_REQUEST, 400, "Unexpected error")

    @app.get("/")
    def index():
        # Lightweight liveness ping; tests don't depend on this but it keeps
        # casual curl-as-smoke-test friendly.
        from response import success_object

        return success_object({"service": "retirement-plan-401k", "status": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # 0.0.0.0 per INSTRUCTION.md startup requirements.
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
