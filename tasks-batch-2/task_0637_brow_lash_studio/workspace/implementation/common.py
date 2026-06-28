"""Shared helpers: system field stamping, pagination, field validation,
decimal rounding (round half up)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import store


# --------------------------------------------------------------------------
# Monetary rounding: round half up to nearest cent / integer (PRD §2.6)
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest integer using round-half-up.
    Returns a Python int. Used for cent amounts."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# System / common fields (PRD §2.5)
# --------------------------------------------------------------------------
def stamp_create(record, with_version=True):
    """Set id (if absent), created_at, and (for versioned entities) updated_at
    and version. Records carry a _seq for deterministic created_at ordering.

    PRD §2.5: created_at recorded once at creation, ISO 8601 UTC with three
    fractional digits; it is a real recording instant (not the logical clock)."""
    from datetime import datetime, timezone
    dt = datetime.now(timezone.utc)
    millis = dt.microsecond // 1000
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % millis)
    if "id" not in record or record["id"] is None:
        record["id"] = store.new_id()
    record["_seq"] = store.next_seq()
    record["created_at"] = iso
    if with_version:
        record["updated_at"] = iso
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version on any mutation (PRD §2.5)."""
    from datetime import datetime, timezone
    dt = datetime.now(timezone.utc)
    millis = dt.microsecond // 1000
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % millis)
    record["updated_at"] = iso
    record["version"] = record.get("version", 1) + 1
    return record


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0
# --------------------------------------------------------------------------
def parse_pagination():
    """Parse limit/offset query params, clamped to PRD bounds.
    Invalid (non-integer) values fall back to defaults."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Return the page slice. items must already be sorted."""
    return items[offset:offset + limit]


def sort_by_created(records):
    """Sort by creation order ascending (PRD §2.3). _seq is the monotonic
    creation sequence, stable even if created_at strings collide."""
    return sorted(records, key=lambda r: r.get("_seq", 0))


# --------------------------------------------------------------------------
# Request body / field validation helpers (ERR_INVALID_REQUEST, 400)
# --------------------------------------------------------------------------
def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body


def bad_request(msg):
    return errors.ApiError(errors.ERR_INVALID_REQUEST, 400, msg)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise bad_request("Field '%s' must be a non-empty string." % field)
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request("Field '%s' must be an integer." % field)
    if minimum is not None and v < minimum:
        raise bad_request("Field '%s' must be >= %s." % (field, minimum))
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad_request("Field '%s' must be a number." % field)
    return v
