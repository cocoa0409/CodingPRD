"""Shared helpers: validation primitives, pagination, money rounding, time."""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import request

from db import db, iso_now, new_id
from errors import err


# --------------------------------------------------------------------------
# Money / rounding (PRD 2.5)
# --------------------------------------------------------------------------
def round_half_up_cents(value):
    """Round a numeric cents value to the nearest whole cent, half rounds up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Time parsing
# --------------------------------------------------------------------------
def parse_iso8601(s):
    """Parse an ISO 8601 instant (trailing Z accepted) to an aware datetime.
    Returns None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Body parsing
# --------------------------------------------------------------------------
def get_json_body():
    """Return the request JSON object, or {} when no body. Raise
    ERR_INVALID_REQUEST when the body is present but not a JSON object."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
def parse_pagination():
    """Parse limit/offset query params. limit default 10, min 1, max 100;
    offset default 0. Malformed -> ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")

    return limit, offset


def paginate(items, serialize):
    """Sort by created_at ASC (creation order), apply limit/offset, build the
    pagination meta block. `items` is the full filtered list of raw records."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset : offset + limit]
    data = [serialize(r) for r in window]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return data, pagination


# --------------------------------------------------------------------------
# System field management
# --------------------------------------------------------------------------
def stamp_new(record):
    """Attach system fields to a freshly created record."""
    now = iso_now()
    record["id"] = record.get("id") or new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and increment version on a mutation (incl. cascades)."""
    record["updated_at"] = iso_now()
    record["version"] = record["version"] + 1


# --------------------------------------------------------------------------
# Validation primitives
# --------------------------------------------------------------------------
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}.")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string.")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} has an invalid value.")
    return v


def require_int_min(body, field, minimum):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}.")
    return v


def optional_int_min(body, field, minimum, default):
    if field not in body or body[field] is None:
        return default
    return require_int_min(body, field, minimum)


# --------------------------------------------------------------------------
# Serialization — strip internal-only keys (those prefixed with "_").
# --------------------------------------------------------------------------
def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}
