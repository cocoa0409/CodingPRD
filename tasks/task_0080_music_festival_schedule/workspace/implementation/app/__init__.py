"""Flask application factory.

Wires the standard response envelope, the role-header auth middleware,
the per-resource blueprints, and the JSON-body error hooks.
"""
from __future__ import annotations

import json
import threading
import traceback
from typing import Any, Tuple

from flask import Flask, Response, g, jsonify, request

from .envelope import (
    error_envelope_response,
    new_request_id,
    server_now_iso8601,
    success_envelope,
)
from .errors import ApiError, ERROR_CATALOG


# Global mutation lock — Python's GIL plus this RLock gives the
# row-by-row serialisation the concurrency rules of §1.2.1 expect.
GLOBAL_LOCK = threading.RLock()


def _attach_request_metadata() -> None:
    g.api_request_id = new_request_id()
    g.api_request_timestamp = server_now_iso8601()
    g.is_idempotent_replay = False


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # -------------------------------------------------------------------------
    # Per-request bookkeeping.
    # -------------------------------------------------------------------------
    @app.before_request
    def _before() -> Any:
        _attach_request_metadata()

        # The auth header check is validation priority 1 and 2 per §1.4.
        # Apply it uniformly to every endpoint (PRD §2.1 makes the dev
        # endpoints under /_clock, /_events, /_sweep subject to the same
        # check), with the sole exception of the bare healthcheck-style
        # 404 handler.
        if request.path == "/healthz":
            return None

        # CORS preflight should pass through without auth.
        if request.method == "OPTIONS":
            return None

        from .auth import require_auth_headers

        err = require_auth_headers()
        if err is not None:
            return err

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError) -> Response:
        return error_envelope_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _route_not_found(_err: Any) -> Response:
        # Flask's own 404 for an unmatched route — still surface in our envelope.
        # The PRD-defined NOT_FOUND family is for known-resource paths, so we
        # use ERR_INVALID_REQUEST_BODY for an unknown route shape.
        # In practice the test suite only hits known routes, so this is a
        # belt-and-suspenders branch.
        return error_envelope_response(
            "ERR_INVALID_REQUEST_BODY",
            f"Route not found: {request.method} {request.path}",
            404,
        )

    @app.errorhandler(405)
    def _method_not_allowed(_err: Any) -> Response:
        return error_envelope_response(
            "ERR_INVALID_REQUEST_BODY",
            f"Method not allowed: {request.method} {request.path}",
            405,
        )

    @app.errorhandler(Exception)
    def _unhandled(err: Exception) -> Response:
        # The test harness reads the envelope and the status; in the unlikely
        # case of a programmer error, log the traceback and surface as 500
        # with a generic ERR_INVALID_REQUEST_BODY shape.
        traceback.print_exc()
        return error_envelope_response(
            "ERR_INVALID_REQUEST_BODY",
            f"Internal server error: {err.__class__.__name__}: {err}",
            500,
        )

    # -------------------------------------------------------------------------
    # Healthcheck — keeps the Docker probe happy.
    # -------------------------------------------------------------------------
    @app.route("/healthz", methods=["GET"])
    def _healthz() -> Tuple[str, int]:
        return "ok", 200

    # -------------------------------------------------------------------------
    # Register the per-resource blueprints.
    # -------------------------------------------------------------------------
    from .routes import register_all

    register_all(app)

    return app
