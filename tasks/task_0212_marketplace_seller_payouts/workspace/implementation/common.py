"""Shared helpers: pagination, datetime parsing, body validation, rounding."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import (
    err,
    ERR_VALIDATION_PAGINATION,
    ERR_INVALID_REQUEST,
)

# Pagination defaults (PRD §2.3 / SCAFFOLD §1.0)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def round_half_up(value):
    """Round a Decimal/number half-up to the nearest whole integer (cents).

    Half-up = away from zero on .5 (PRD §2.5)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_pagination():
    """Return (limit, offset). Raises ERR_VALIDATION_PAGINATION on out-of-range
    values (PRD §2.3)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_PAGINATION, "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err(ERR_VALIDATION_PAGINATION, "limit out of range (1..100).")

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_PAGINATION, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_VALIDATION_PAGINATION, "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Return (page_items, pagination_meta). `items` already filtered & sorted."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_by_created(items):
    """List results are ordered by created_at ascending (PRD §2.3).

    created_at strings are ISO 8601 and lexically ordered; ties broken by id
    for stable ordering across identical timestamps."""
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


def get_json_body():
    """Return the parsed JSON object body, or {} if absent. Raises
    ERR_INVALID_REQUEST if the body is present but not a JSON object."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def parse_iso8601(value):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.

    Raises ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str) or not value:
        raise err(ERR_INVALID_REQUEST, "Expected an ISO 8601 timestamp string.")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Malformed ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, fields):
    """Ensure each named field is present (not None) in the body."""
    for f in fields:
        if body.get(f) is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}.")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}.")


def require_int(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer.")
    if minimum is not None and value < minimum:
        raise err(ERR_INVALID_REQUEST, f"{field} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise err(ERR_INVALID_REQUEST, f"{field} must be <= {maximum}.")
    return value


def require_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err(ERR_INVALID_REQUEST, f"{field} must be a non-empty string.")
    return value
