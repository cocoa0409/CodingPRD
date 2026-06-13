"""Shared helpers: pagination parsing, body access, field validation, serialization."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import request

from db import iso
from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict (empty dict if none / malformed-but-empty)."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        # Malformed JSON or non-object body -> treat as invalid request.
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    """Parse limit/offset query params. Out-of-range -> ERR_VALIDATION_PAGINATION."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err(
                "ERR_VALIDATION_PAGINATION",
                "limit must be between {} and {}.".format(
                    PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
                ),
            )

    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_VALIDATION_PAGINATION", "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list and return (window, total_count)."""
    total = len(items)
    window = items[offset : offset + limit]
    return window, total


def sort_by_creation(items):
    """Sort records ascending by creation order (PRD §2.3)."""
    return sorted(items, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Field validation (priority 4: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: {}.".format(n))


def as_int_nonneg(body, name, required=True):
    """Read an integer field that must be >= 0 when present (no bool)."""
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: {}.".format(name))
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field {} must be an integer.".format(name))
    if v < 0:
        raise err("ERR_INVALID_REQUEST", "Field {} must be non-negative.".format(name))
    return v


def as_int(body, name, required=True):
    """Read an integer field (any sign) (no bool)."""
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: {}.".format(name))
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field {} must be an integer.".format(name))
    return v


def as_str(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: {}.".format(name))
        return None
    v = body[name]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a string.".format(name))
    return v


def as_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a boolean.".format(name))
    return v


def as_enum(body, name, allowed, required=True):
    v = as_str(body, name, required=required)
    if v is None:
        return None
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field {} is out of range.".format(name))
    return v


# ---------------------------------------------------------------------------
# Rounding (PRD §2.6)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number half-up to an integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div_decimal(numerator, denominator):
    """Floor of an exact division, returned as an int."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Serialization — strip internal bookkeeping (_seq) and format timestamps.
# ---------------------------------------------------------------------------
_TS_FIELDS = {
    "created_at",
    "updated_at",
    "origination_at",
    "term_end_at",
    "grace_end_at",
    "reserved_from_at",
    "reserved_until_at",
    "last_layaway_end_at",
    "current_utc",
}


def serialize(record):
    """Public projection of an internal record: drop _seq, format datetime fields."""
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        if k in _TS_FIELDS and v is not None and not isinstance(v, str):
            out[k] = iso(v)
        else:
            out[k] = v
    return out
