"""Generic shape-of-input validators."""

from __future__ import annotations

from typing import Any

from flask import request

from errors import APIError


def get_body() -> dict[str, Any]:
    if request.method in ("POST", "PATCH", "PUT") and request.content_length:
        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            raise APIError("ERR_VALIDATION", "Body is not valid JSON.")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise APIError("ERR_VALIDATION", "Body must be a JSON object.")
        return body
    body = request.get_json(force=True, silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError("ERR_VALIDATION", "Body must be a JSON object.")
    return body


def require_str(body: dict, key: str, *, min_length: int = 1, max_length: int | None = None) -> str:
    val = body.get(key)
    if not isinstance(val, str) or len(val) < min_length:
        raise APIError("ERR_VALIDATION", f"'{key}' is required and must be a string.")
    if max_length is not None and len(val) > max_length:
        raise APIError("ERR_VALIDATION", f"'{key}' exceeds maximum length {max_length}.")
    return val


def require_number(body: dict, key: str) -> float:
    val = body.get(key)
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise APIError("ERR_VALIDATION", f"'{key}' is required and must be numeric.")
    return float(val)


def require_int(body: dict, key: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    val = body.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise APIError("ERR_VALIDATION", f"'{key}' is required and must be an integer.")
    if minimum is not None and val < minimum:
        raise APIError("ERR_VALIDATION", f"'{key}' must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise APIError("ERR_VALIDATION", f"'{key}' must be <= {maximum}.")
    return val


def opt_int(body: dict, key: str) -> int | None:
    if key not in body or body[key] is None:
        return None
    val = body[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise APIError("ERR_VALIDATION", f"'{key}' must be an integer when present.")
    return val


def opt_str(body: dict, key: str) -> str | None:
    if key not in body or body[key] is None:
        return None
    val = body[key]
    if not isinstance(val, str):
        raise APIError("ERR_VALIDATION", f"'{key}' must be a string when present.")
    return val


def parse_pagination() -> tuple[int, int]:
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise APIError("ERR_VALIDATION", "limit/offset must be integers.")
    if limit < 1 or limit > 100:
        raise APIError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise APIError("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset
