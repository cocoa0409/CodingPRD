"""Response envelope, request-id injection, and centralized error handling."""
from __future__ import annotations

import json
from typing import Any

from flask import Flask, Response, g, request

from .clock import Clock
from .errors import ApiError, ERROR_STATUS
from .ids import new_request_id


def _meta_base() -> dict[str, Any]:
    clock: Clock = _current_clock()
    return {
        "api_request_id": getattr(g, "request_id", new_request_id()),
        "api_request_timestamp": clock.now_iso(),
    }


def _current_clock() -> Clock:
    from flask import current_app

    return current_app.config["CLOCK"]


def envelope_object(data: dict[str, Any], status: int = 200) -> Response:
    body = {"meta": _meta_base(), "response_type": "object", "data": data}
    return _json_response(body, status)


def envelope_array(
    data: list[Any],
    *,
    limit: int,
    offset: int,
    total_count: int,
    status: int = 200,
) -> Response:
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(data)) < total_count
    body = {"meta": meta, "response_type": "array", "data": data}
    return _json_response(body, status)


def envelope_error(error_id: str, message: str, status: int) -> Response:
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _json_response(body, status)


def _scrub(value):
    """Recursively drop underscore-prefixed keys (private record state)."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(value, list):
        return [_scrub(x) for x in value]
    return value


def _json_response(body: dict[str, Any], status: int) -> Response:
    return Response(
        json.dumps(_scrub(body), separators=(",", ":")),
        status=status,
        mimetype="application/json",
    )


def install_envelope_handlers(app: Flask) -> None:
    @app.before_request
    def _assign_request_id():
        g.request_id = new_request_id()

    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return envelope_error(exc.error_id, exc.message, exc.status_code)

    @app.errorhandler(404)
    def _not_found(_):
        return envelope_error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method(_):
        return envelope_error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(400)
    def _bad(_):
        return envelope_error("ERR_VALIDATION", "Invalid request", 422)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        # Surface programmer errors as ERR_VALIDATION rather than leak HTML.
        return envelope_error("ERR_VALIDATION", f"Unhandled: {exc}", 422)


def expect_json_body() -> dict[str, Any]:
    """Return the parsed JSON body, or raise ERR_VALIDATION."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Malformed JSON body")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "Body must be a JSON object")
    return parsed
