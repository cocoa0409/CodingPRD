"""Response envelope construction and Flask error handlers.

Matches the structure defined in SCAFFOLD.yaml > response_envelope and PRD §2.2:

    Success:
        {
          "meta": { "api_request_id": "req_...", "api_request_timestamp": "...Z",
                    "limit": 10, "offset": 0, "total_count": N, "has_more": bool },
          "response_type": "object" | "array",
          "data": { ... } | [ ... ]
        }

    Error:
        {
          "meta": { "api_request_id": "req_...", "api_request_timestamp": "...Z" },
          "response_type": "error",
          "data": { "error_id": "...", "message": "..." }
        }
"""
from __future__ import annotations

import secrets
import string
from typing import Any, Optional

from flask import jsonify

from app.errors import APIError
from app.timeutil import now_iso


_REQUEST_ID_ALPHABET = string.ascii_uppercase + string.digits


def _new_request_id() -> str:
    suffix = "".join(secrets.choice(_REQUEST_ID_ALPHABET) for _ in range(20))
    return f"req_{suffix}"


def _meta(pagination: Optional[dict] = None) -> dict:
    meta = {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data: Any, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items: list, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = offset + limit < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def _handle_api_error(err: APIError):
        return error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_404(err):
        return error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def _handle_405(err):
        return error("ERR_VALIDATION", "Method not allowed.", 400)

    @app.errorhandler(400)
    def _handle_400(err):
        return error("ERR_VALIDATION", "Malformed request body.", 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        # Defensive: never let an unhandled exception escape as a non-envelope 500.
        if isinstance(err, APIError):
            return error(err.error_id, err.message, err.http_status)
        return error("ERR_VALIDATION", f"Unexpected server error: {type(err).__name__}: {err}", 400)
