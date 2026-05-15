"""Shared route helpers."""
from __future__ import annotations

from functools import wraps
from typing import Any

from flask import jsonify, request

from ..errors import ApiError
from ..response import paginate, success_envelope
from ..store import LOCK


def get_json_body() -> dict[str, Any]:
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception as exc:  # noqa: BLE001
        raise ApiError("ERR_INVALID_INPUT", f"Invalid JSON: {exc}")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_INPUT", "Request body must be a JSON object.")
    return body


def ok(data: Any, status: int = 200):
    body = success_envelope(data, response_type="object")
    return jsonify(body), status


def ok_list(items: list[Any], limit: int, offset: int):
    sliced, pag = paginate(items, limit, offset)
    body = success_envelope(sliced, response_type="array", pagination=pag)
    return jsonify(body), 200


def with_lock(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with LOCK:
            return func(*args, **kwargs)

    return wrapper
