"""Flask application factory + entry point.

- Reads PORT (default 10000), binds 0.0.0.0, threaded.
- Produces the §2.2 error envelope for every error, including framework 404s.
- Registers route blueprints DEFENSIVELY: a missing module (the other half of
  the implementation may be absent) is skipped, never fatal.
- Lazy time-based effects (services.expiry.evaluate_time_based_effects, owned
  by another module set) are evaluated around requests: before each /v1
  request (so reads and gates see fresh posture/expiry state) and after every
  mutating request.
"""

import importlib
import os
import traceback

from flask import Flask, request

from errors import ApiError, ERR_INVALID_REQUEST
from response import err
from services.validation import run_lazy_effects

ROUTE_MODULES = (
    "properties",
    "policies",
    "banner_configs",
    "vendors",
    "tag_rules",
    "visitors",
    "consent",
    "dns",
    "scans",
    "sweeps",
)

MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return err(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_not_found(exc):
        return err(ERR_INVALID_REQUEST, "Route not found", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(exc):
        return err(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        traceback.print_exc()
        return err(ERR_INVALID_REQUEST, "Internal server error", 500)

    @app.before_request
    def _evaluate_effects_before():
        # Before rendering any GET (and before mutation gates): apply lazy
        # expiry/escalation so reads and posture decisions are current (§2.4).
        if request.path.startswith("/v1"):
            run_lazy_effects()

    @app.after_request
    def _evaluate_effects_after(response):
        # After every state-mutating request, settle lazy effects.
        if request.method in MUTATING_METHODS:
            run_lazy_effects()
        return response

    for name in ROUTE_MODULES:
        try:
            module = importlib.import_module(f"routes.{name}")
        except ImportError:
            continue
        blueprint = getattr(module, "bp", None)
        if blueprint is not None:
            app.register_blueprint(blueprint)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
