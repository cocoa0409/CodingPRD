"""Response envelope + global Flask error handlers.

PRD §2.2: every successful response carries the canonical envelope
{ meta: { api_request_id, api_request_timestamp, [pagination]... },
  response_type: "object" | "array",
  data: ... }
Every error carries response_type: "error" and a data object with
{ error_id, message }.
"""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from app.errors import APIError


_ALPHANUM = string.ascii_uppercase + string.ascii_lowercase + string.digits


def _request_id() -> str:
    suffix = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{suffix}"


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
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
    has_more = (offset + limit) < total
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
        return error_response("ERR_RESOURCE_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response("ERR_RESOURCE_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(400)
    def handle_400(_err):
        return error_response("ERR_BAD_REQUEST", 400, "Malformed request")

    @app.errorhandler(HTTPException)
    def handle_http(err: HTTPException):
        return error_response("ERR_BAD_REQUEST", 400, err.description or "HTTP error")

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Last-ditch handler — keep deterministic body shape for tests.
        return error_response("ERR_BAD_REQUEST", 400, f"Unexpected error: {err}")
