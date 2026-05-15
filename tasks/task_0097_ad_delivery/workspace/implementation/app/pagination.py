"""Offset/limit pagination helpers."""
from flask import request

from .errors import ApiError


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(value, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", f"Parameter '{name}' must be an integer.")


def get_pagination() -> tuple[int, int]:
    limit = _parse_int(request.args.get("limit"), DEFAULT_LIMIT, "limit")
    offset = _parse_int(request.args.get("offset"), DEFAULT_OFFSET, "offset")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"Parameter 'limit' must be between {MIN_LIMIT} and {MAX_LIMIT}.",
        )
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "Parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows: list, limit: int, offset: int) -> tuple[list, dict]:
    total = len(rows)
    page = rows[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def sort_by_created_asc(rows: list) -> list:
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
