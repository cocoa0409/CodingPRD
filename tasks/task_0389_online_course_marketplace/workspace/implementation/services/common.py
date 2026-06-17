"""Shared helpers: mutation bookkeeping, rounding, validation primitives."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

import clock
from db import db, iso
from errors import err


# --------------------------------------------------------------------------
# System-managed common fields (PRD §2.4)
# --------------------------------------------------------------------------

def stamp_create(rec, mutable=True):
    """Set created_at/updated_at/version on a brand-new record.

    created_at uses the LOGICAL clock (domain instant). version starts at 1.
    Immutable records (Certificate, RevenueLedgerEntry) get only created_at.
    """
    now = clock.now()
    rec["created_at"] = iso(now)
    rec["_seq"] = db.next_seq()  # internal tie-breaker for created_at ASC sort
    if mutable:
        rec["updated_at"] = iso(now)
        rec["version"] = 1
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at, bump version by 1 (PRD §2.4)."""
    rec["updated_at"] = iso(clock.now())
    rec["version"] = rec.get("version", 0) + 1


# --------------------------------------------------------------------------
# Rounding (PRD §2.6)
# --------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a numeric value to the nearest whole cent, half-up. Returns int."""
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def round_4dp(value):
    """Round to 4 decimal places, half-up. Returns float."""
    d = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(d)


def round_2dp(value):
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


# --------------------------------------------------------------------------
# Datetime parsing for time-sensitive fields
# --------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime.

    Accepts trailing 'Z' or an explicit offset. Naive strings are treated as
    UTC. Raises ERR_INVALID_REQUEST on a malformed value.
    """
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Expected an ISO 8601 datetime string.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Malformed ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    from datetime import timedelta
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Field-level input validation primitives (ERR_INVALID_REQUEST, §2.11 lowest)
# --------------------------------------------------------------------------

def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}.")
    return body[name]


def as_int(value, name):
    # bool is a subclass of int; reject it as a numeric for safety.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer.")
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a number.")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean.")
    return value


def as_str(value, name):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a string.")
    return value


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Sort by created_at ASC (insertion / _seq order).
# --------------------------------------------------------------------------

def paginate(items, args):
    """Sort by created_at ASC then apply limit/offset.

    `items` is a list of records. Returns (page_items, pagination_meta).
    Invalid limit/offset values are rejected with ERR_INVALID_REQUEST.
    """
    ordered = sorted(items, key=lambda r: r.get("_seq", 0))
    total = len(ordered)

    limit = _parse_int_param(args.get("limit"), default=10, name="limit")
    offset = _parse_int_param(args.get("offset"), default=0, name="offset")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")

    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def _parse_int_param(raw, default, name):
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer.")
