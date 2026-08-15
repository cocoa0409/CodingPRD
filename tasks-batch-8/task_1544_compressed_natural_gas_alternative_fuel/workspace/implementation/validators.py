"""Shared request-shape validation helpers (stage 3) and pagination parsing."""
from __future__ import annotations

from flask import request

from db import parse_iso, parse_month
from errors import ApiError, ERR_INVALID_REQUEST
from services.core import to_decimal


def body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def require_fields(data: dict, fields: list[str]) -> None:
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def require_string(data: dict, field: str) -> str:
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a non-empty string")
    return v


def require_enum(data: dict, field: str, allowed: set[str]) -> str:
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be one of {sorted(allowed)}")
    return v


def require_positive_int(data: dict, field: str) -> int:
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a positive integer")
    return v


def require_nonnegative_int(data: dict, field: str) -> int:
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a non-negative integer")
    return v


def require_positive_number(data: dict, field: str):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a positive number")
    try:
        d = to_decimal(v)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be numeric")
    if d <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be greater than zero")
    return d


def optional_number(data: dict, field: str):
    """Return Decimal or None. Present-but-null counts as absent."""
    if field not in data or data[field] is None:
        return None
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be numeric")
    try:
        return to_decimal(v)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be numeric")


def require_datetime(data: dict, field: str):
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be an ISO 8601 datetime string")
    try:
        return parse_iso(v)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} is not a valid ISO 8601 datetime")


def require_month(data: dict, field: str) -> str:
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a YYYY-MM month string")
    try:
        parse_month(v)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {field} must be a well-formed YYYY-MM month")
    return v


def parse_pagination() -> tuple[int, int]:
    """limit (default 10, min 1, max 100), offset (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    """Apply offset/limit. Returns (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
