"""Common route helpers."""
from __future__ import annotations

from typing import Any

from flask import jsonify, request

from ..errors import ApiError
from ..response import success_envelope


def get_json_body(allow_empty: bool = True) -> dict[str, Any]:
    """Parse the request JSON body; tolerate missing body for endpoints that accept none."""
    if request.method == "GET":
        return {}
    if not request.data:
        if allow_empty:
            return {}
        raise ApiError("ERR_VALIDATION_FAILED", "Request body required.")
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION_FAILED", "Invalid JSON body.")
    if body is None:
        if allow_empty:
            return {}
        raise ApiError("ERR_VALIDATION_FAILED", "Request body required.")
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION_FAILED", "Body must be a JSON object.")
    return body


def ok(data, status: int = 200, response_type: str = "object", pagination: dict[str, Any] | None = None):
    body = success_envelope(data, response_type=response_type, pagination=pagination)
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_ok(items, pagination):
    return ok(items, response_type="array", pagination=pagination)
