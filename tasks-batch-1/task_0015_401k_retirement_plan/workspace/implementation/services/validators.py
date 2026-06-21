"""Input validation helpers — all raise ERR_INVALID_REQUEST on shape failures
unless a more specific error_id is required by SCAFFOLD §1.4."""

from __future__ import annotations

from typing import Any

from errors import APIError, ERR_INVALID_REQUEST


def require_dict(body: Any) -> dict:
    if body is None:
        # An empty body is fine for some endpoints — caller decides via require_keys.
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return body


def require_keys(body: dict, keys: list[str]) -> None:
    for k in keys:
        if k not in body or body[k] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"missing required field '{k}'")


def require_str(body: dict, key: str, *, allow_missing: bool = False) -> str | None:
    v = body.get(key)
    if v is None:
        if allow_missing:
            return None
        raise APIError(ERR_INVALID_REQUEST, 400, f"missing required field '{key}'")
    if not isinstance(v, str) or not v:
        raise APIError(ERR_INVALID_REQUEST, 400, f"field '{key}' must be a non-empty string")
    return v


def require_int(
    body: dict,
    key: str,
    *,
    allow_missing: bool = False,
    minimum: int | None = None,
    maximum: int | None = None,
    strictly_positive: bool = False,
) -> int | None:
    v = body.get(key)
    if v is None:
        if allow_missing:
            return None
        raise APIError(ERR_INVALID_REQUEST, 400, f"missing required field '{key}'")
    # Booleans are subtypes of int in Python — reject them explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"field '{key}' must be an integer")
    if strictly_positive and v <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, f"field '{key}' must be > 0")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"field '{key}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"field '{key}' must be <= {maximum}")
    return v


def require_enum(body: dict, key: str, allowed: set[str], *, allow_missing: bool = False) -> str | None:
    v = body.get(key)
    if v is None:
        if allow_missing:
            return None
        raise APIError(ERR_INVALID_REQUEST, 400, f"missing required field '{key}'")
    if v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 400, f"field '{key}' must be one of {sorted(allowed)}")
    return v
