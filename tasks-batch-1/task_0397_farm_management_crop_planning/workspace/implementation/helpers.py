"""Shared helpers: body parsing, field validation, pagination, money rounding.

Validation maps to PRD §2.3 (pagination), §2.8 (precision/rounding), §2.10
(request-shape validation -> ERR_INVALID_REQUEST).
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err

# Pagination defaults (SCAFFOLD §1.0, PRD §2.3)
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when absent/empty.

    A body that is present but not a JSON object is an ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        # Empty/whitespace-only body is acceptable for no-input endpoints.
        if request.data.strip() == b"":
            return {}
        raise err("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def round2(value):
    """Round to two decimal places, round-half-up (PRD §2.8). Returns a float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def as_number(value):
    """Accept int/float (but not bool, not numeric strings)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"Field '{name}' must be a non-empty string.")
    return v


def require_number(body, name):
    v = as_number(body.get(name))
    if v is None:
        raise err("ERR_INVALID_REQUEST", f"Field '{name}' must be a number.")
    return v


def require_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field '{name}' must be an integer.")
    return v


def require_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field '{name}' must be one of {sorted(allowed)}.")
    return v


def optional_bool(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field '{name}' must be a boolean.")
    return v


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Out-of-range -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET

    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise err(
                "ERR_INVALID_REQUEST",
                f"limit must be between {PAGE_MIN_LIMIT} and {PAGE_MAX_LIMIT}.",
            )

    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at asc (then by creation sequence for ties), then slice.

    PRD §2.3: every list is sorted by created_at ascending.
    Returns (page_items, total_count).
    """
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total
