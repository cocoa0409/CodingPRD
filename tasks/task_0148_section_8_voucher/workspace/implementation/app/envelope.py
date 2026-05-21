"""Response envelope + global Flask error handlers."""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from app.errors import APIError


_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id() -> str:
    suffix = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{suffix}"


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    # ISO 8601 UTC with milliseconds and trailing Z.
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _make_meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success_response(
    data: Any,
    *,
    response_type: str = "object",
    status: int = 200,
    pagination: Optional[dict] = None,
):
    meta = _make_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def list_response(items: Iterable[dict], *, limit: int, offset: int, total: int, status: int = 200):
    has_more = offset + limit < total
    return success_response(
        list(items),
        response_type="array",
        status=status,
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": has_more,
        },
    )


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": _make_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def register_error_handlers(app: Flask) -> None:

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(_err):
        return error_response("ERR_VALIDATION", 422, "Malformed request body")

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        return error_response("ERR_VALIDATION", 422, err.description or "HTTP error")

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Last-ditch: keep tests deterministic instead of returning a 500 stack trace.
        return error_response("ERR_VALIDATION", 422, f"Unexpected error: {err}")
