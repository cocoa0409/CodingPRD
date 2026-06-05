"""Shared service helpers: serialization, pagination, request-body validation,
money rounding.
"""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors

# Internal bookkeeping keys never exposed in API responses.
_INTERNAL_KEYS = {"_seq"}


def round_half_up(value):
    """Round a numeric value to the nearest whole cent, half-up (PRD §2.5).

    value is a Decimal (or convertible). Returns a Python int.
    """
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_rate(base_cents, rate):
    """Apply a decimal rate once to an integer-cent base, round half-up to a
    whole cent (PRD §2.5: sum-then-round, once over the whole base)."""
    return round_half_up(Decimal(int(base_cents)) * Decimal(str(rate)))


def serialize(record, drop=None):
    """Strip internal keys (and any explicitly dropped keys) from a record for
    the response body."""
    drop_set = set(_INTERNAL_KEYS)
    if drop:
        drop_set |= set(drop)
    return {k: v for k, v in record.items() if k not in drop_set}


# --- Pagination (PRD §2.3) ---------------------------------------------------
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def parse_pagination():
    """Read & validate limit/offset query params (PRD §2.3).

    limit defaults to 10, min 1, max 100. offset defaults to 0. Out-of-range or
    non-integer values are rejected with ERR_INVALID_REQUEST.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = PAGINATION_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise errors.invalid_request(
                "limit must be between %d and %d."
                % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX)
            )

    if raw_offset is None:
        offset = PAGINATION_OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")

    return limit, offset


def paginate(records, limit, offset):
    """Order by created_at ascending (creation order via _seq), slice, and
    return (page, pagination_meta) (PRD §2.3)."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


# --- Request body access -----------------------------------------------------
def get_body():
    """Return the JSON body as a dict, or {} when absent. A non-object JSON
    body (e.g. a list or scalar) is an invalid request."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body must be valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


# --- Field validation helpers (ERR_INVALID_REQUEST, PRD §3.9 priority 14) ----
def require_present(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Missing required field: %s." % field)
    return body[field]


def require_nonempty_string(body, field):
    val = require_present(body, field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("%s must be a non-empty string." % field)
    return val


def _is_bool(v):
    return isinstance(v, bool)


def require_int(body, field, minimum=None):
    val = require_present(body, field)
    # bool is a subclass of int; reject it explicitly.
    if _is_bool(val) or not isinstance(val, int):
        raise errors.invalid_request("%s must be an integer." % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("%s must be >= %d." % (field, minimum))
    return val


def optional_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if _is_bool(val) or not isinstance(val, int):
        raise errors.invalid_request("%s must be an integer." % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("%s must be >= %d." % (field, minimum))
    return val


def require_number(body, field):
    val = require_present(body, field)
    if _is_bool(val) or not isinstance(val, (int, float)):
        raise errors.invalid_request("%s must be a number." % field)
    return val


def require_enum(body, field, allowed):
    val = require_present(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(
            "%s must be one of %s." % (field, sorted(allowed))
        )
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(
            "%s must be one of %s." % (field, sorted(allowed))
        )
    return val


def require_datetime_str(body, field):
    """Accept an ISO 8601 datetime string. Stored verbatim; only ordering
    against the sibling endpoint matters, and that compares the parsed values."""
    val = require_present(body, field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("%s must be an ISO 8601 datetime string." % field)
    if parse_dt(val) is None:
        raise errors.invalid_request("%s must be a valid ISO 8601 datetime." % field)
    return val


def parse_dt(value):
    """Parse an ISO 8601 datetime string to a comparable datetime, or None if
    it cannot be parsed. Handles a trailing 'Z' (UTC)."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None
