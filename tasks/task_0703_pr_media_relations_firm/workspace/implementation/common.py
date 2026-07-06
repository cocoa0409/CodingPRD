"""Shared helpers: common-field stamping, validation primitives, pagination.

Common system fields (PRD 2.4):
  id, created_at, updated_at, version (begins at 1, +1 on every mutation).
Outlet is the lean exception: only id + created_at (no updated_at, no version).
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from clock import clock, format_iso
from errors import err


# ----------------------------------------------------------------------------
# Common field stamping
# ----------------------------------------------------------------------------
def new_record(extra=None, with_version=True):
    """Create a record with id/created_at/updated_at/version common fields.

    Note: created_at/updated_at use the logical clock, since these are business
    timestamps of resource lifecycle events driven by the test clock.
    """
    now = clock.now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["version"] = 1
    if extra:
        rec.update(extra)
    return rec


def new_outlet_record(extra=None):
    """Outlet: only id + created_at common fields (PRD 2.4)."""
    rec = {
        "id": db.new_id(),
        "created_at": clock.now_iso(),
        "_seq": db.next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Refresh updated_at and bump version (PRD 2.4, 2.5)."""
    rec["updated_at"] = clock.now_iso()
    if "version" in rec:
        rec["version"] += 1


# ----------------------------------------------------------------------------
# Request body parsing & validation primitives
# ----------------------------------------------------------------------------
def get_json_body():
    """Parse the JSON request body, defaulting to {} for empty bodies.

    A malformed (non-empty, non-JSON) body is a request well-formedness failure.
    """
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_str(body, field, allow_empty=False):
    val = body.get(field)
    if not isinstance(val, str) or (not allow_empty and val.strip() == ""):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty string")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  f"Field '{field}' must be one of {sorted(allowed)}")
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body.get(field) is None:
        return default
    return require_enum(body, field, allowed)


def require_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    # bool is a subclass of int; reject it explicitly.
    if not isinstance(val, int) or isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be <= {maximum}")
    return val


def require_number(body, field, minimum=None, exclusive_min=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a number")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}")
    if exclusive_min is not None and val <= exclusive_min:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be > {exclusive_min}")
    return val


def require_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a boolean")
    return val


def require_datetime(body, field):
    """Require an ISO-8601 datetime string; return the parsed aware datetime."""
    val = body.get(field)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an ISO-8601 string")
    try:
        return parse_dt(val)
    except Exception:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a valid ISO-8601 datetime")


def parse_dt(s):
    from clock import _parse_iso
    return _parse_iso(s)


# ----------------------------------------------------------------------------
# Reference resolution (existence checks)
# ----------------------------------------------------------------------------
def get_or_404(collection, rid):
    """Path existence check (priority 3): ERR_NOT_FOUND if absent."""
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def ref_or_404(collection, rid, field):
    """FK body reference existence (priority 4): ERR_REFERENCE_NOT_FOUND."""
    if not isinstance(rid, str):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a string id")
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_REFERENCE_NOT_FOUND",
                  f"Referenced resource for '{field}' does not exist")
    return rec


# ----------------------------------------------------------------------------
# Pagination & listing (PRD 2.3)
# ----------------------------------------------------------------------------
def parse_pagination():
    """Parse limit/offset query params with defaults limit=10 (1..100), offset=0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by creation order ascending, slice, and return (page, meta)."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# ----------------------------------------------------------------------------
# Money / precision
# ----------------------------------------------------------------------------
def round_half_up_cents(real_value):
    """Round a real number of cents to a whole-cent integer, round-half-up."""
    return int(Decimal(str(real_value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(real_value):
    """Round a ratio to 4 decimal places, round-half-up; return a float."""
    return float(Decimal(str(real_value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
