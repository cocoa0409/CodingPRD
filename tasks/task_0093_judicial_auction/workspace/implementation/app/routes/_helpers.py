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
        raise ApiError("ERR_VALIDATION", f"Invalid JSON: {exc}")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
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


def require_field(body: dict[str, Any], field: str) -> Any:
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
    return body[field]


def require_str(body: dict[str, Any], field: str) -> str:
    value = require_field(body, field)
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", f"{field} must be a string.")
    if not value.strip():
        raise ApiError("ERR_VALIDATION", f"{field} must be non-empty.")
    return value


def require_int(body: dict[str, Any], field: str) -> int:
    value = require_field(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", f"{field} must be an integer.")
    return value


def require_enum(body: dict[str, Any], field: str, allowed: set[str]) -> str:
    value = require_str(body, field)
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", f"{field} must be one of {sorted(allowed)}.")
    return value


def check_version(entity: dict[str, Any], body: dict[str, Any]) -> None:
    """OCC: if body carries `version`, it must match entity['version']."""
    if "version" not in body or body["version"] is None:
        return
    try:
        v = int(body["version"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "version must be an integer.")
    if v != int(entity.get("version", 0)):
        raise ApiError("ERR_VERSION_CONFLICT", "Optimistic concurrency conflict.")
