"""Input validation helpers (body schema, enums, types)."""

from __future__ import annotations

from decimal import Decimal

from errors import APIError, ERR_VALIDATION
from utils import parse_ts, to_money


def require_body(body):
    """Body must be a JSON dict."""
    if not isinstance(body, dict):
        raise APIError(ERR_VALIDATION, "Request body must be a JSON object", 422)
    return body


def require_field(body: dict, name: str):
    """Field must be present and non-None."""
    if name not in body or body[name] is None:
        raise APIError(ERR_VALIDATION, f"Field {name!r} is required", 422)
    return body[name]


def get_str(body: dict, name: str, *, required: bool = True, allow_empty: bool = False,
            default=None):
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_VALIDATION, f"Field {name!r} is required", 422)
        return default
    v = body[name]
    if not isinstance(v, str):
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be a string", 422)
    if not allow_empty and v == "":
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be non-empty", 422)
    return v


def get_int(body: dict, name: str, *, required: bool = True, min_value=None, default=None):
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_VALIDATION, f"Field {name!r} is required", 422)
        return default
    v = body[name]
    # bool is subclass of int in Python — reject bool explicitly
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be an integer", 422)
    if min_value is not None and v < min_value:
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be >= {min_value}", 422)
    return v


def get_bool(body: dict, name: str, *, required: bool = False, default=False):
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_VALIDATION, f"Field {name!r} is required", 422)
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be a boolean", 422)
    return v


def get_money(body: dict, name: str, *, required: bool = True, non_negative: bool = True,
              default=None) -> Decimal | None:
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_VALIDATION, f"Field {name!r} is required", 422)
        return default
    v = body[name]
    if isinstance(v, bool):
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be a number", 422)
    if not isinstance(v, (int, float, str, Decimal)):
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be a number", 422)
    d = to_money(v)
    if d is None:
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be a number", 422)
    if non_negative and d < 0:
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be non-negative", 422)
    return d


def get_enum(body: dict, name: str, allowed, *, required: bool = True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_VALIDATION, f"Field {name!r} is required", 422)
        return default
    v = body[name]
    if v not in allowed:
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be one of {sorted(allowed)}", 422)
    return v


def get_datetime(body: dict, name: str, *, required: bool = True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise APIError(ERR_VALIDATION, f"Field {name!r} is required", 422)
        return default
    v = body[name]
    if not isinstance(v, str):
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be an ISO 8601 string", 422)
    parsed = parse_ts(v)
    if parsed is False or parsed is None:
        raise APIError(ERR_VALIDATION, f"Field {name!r} must be a valid ISO 8601 timestamp", 422)
    return parsed
