"""Shared helpers: auth, time parsing, validation primitives, pagination."""
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store
from errors import err
from response import now_iso

RECOGNIZED_ROLES = {"VenueAdmin", "Coordinator", "Client", "FinanceOfficer"}


# --------------------------------------------------------------------------
# Auth (PRD §2.1) — validation priority 1 & 2.
# --------------------------------------------------------------------------
def authenticate():
    """Validate the X-User-ID / X-User-Role header pair. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized authentication headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", f"Role {role} may not perform this operation")


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def parse_datetime(value, field):
    """Parse an ISO 8601 datetime. Raise ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO8601 datetime string")
    raw = value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_date(value, field):
    """Parse a YYYY-MM-DD calendar date. Raise ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a YYYY-MM-DD date string")
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid YYYY-MM-DD date")


def clock_now():
    return store.clock


def clock_date():
    return store.clock.astimezone(timezone.utc).date()


def dt_to_iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# --------------------------------------------------------------------------
# Money / rounding
# --------------------------------------------------------------------------
def round_half_up(amount):
    """Round a numeric amount to whole cents using round-half-up."""
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(amount_cents, fraction):
    """round_half_up(amount_cents * fraction)."""
    return round_half_up(Decimal(str(amount_cents)) * Decimal(str(fraction)))


# --------------------------------------------------------------------------
# Body / field validation (priority 6)
# --------------------------------------------------------------------------
def get_body():
    if request.method in ("GET", "DELETE") and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_string(body, field, min_len=1, max_len=None):
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a string")
    if len(v) < min_len:
        raise err("ERR_INVALID_REQUEST", f"{field} too short")
    if max_len is not None and len(v) > max_len:
        raise err("ERR_INVALID_REQUEST", f"{field} too long")
    return v


def require_enum(body, field, choices):
    v = body.get(field)
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(choices)}")
    return v


def require_int(body, field, min_val=None, max_val=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    if min_val is not None and v < min_val:
        raise err("ERR_INVALID_REQUEST", f"{field} below minimum {min_val}")
    if max_val is not None and v > max_val:
        raise err("ERR_INVALID_REQUEST", f"{field} above maximum {max_val}")
    return v


def require_number(body, field, min_val=None, max_val=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number")
    if min_val is not None and v < min_val:
        raise err("ERR_INVALID_REQUEST", f"{field} below minimum {min_val}")
    if max_val is not None and v > max_val:
        raise err("ERR_INVALID_REQUEST", f"{field} above maximum {max_val}")
    return v


# --------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10 [1,100], offset default 0 [0,..]
# --------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_LIMIT", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_LIMIT", "limit out of range [1,100]")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_LIMIT", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION_LIMIT", "offset out of range [0,..]")

    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; returns the page slice and total."""
    total = len(items)
    return items[offset:offset + limit], total


# --------------------------------------------------------------------------
# System field stamping
# --------------------------------------------------------------------------
def stamp_create(record, with_version=True):
    ts = now_iso()
    record["created_at"] = ts
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
