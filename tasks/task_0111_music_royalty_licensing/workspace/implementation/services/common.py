"""Shared helpers: timestamps, datetime parsing, rounding, common-field stamping,
input validation, and pagination."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

import db
from errors import fail, ERR_INVALID_REQUEST


# ----------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ----------------------------------------------------------------------------
def stamp_create(rec):
    """Set id, created_at, updated_at, version on a freshly created entity that
    carries the full common-field set."""
    now = db.now_iso()
    rec["id"] = db.new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and increment version on a mutation (PRD §2.4)."""
    rec["updated_at"] = db.now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ----------------------------------------------------------------------------
# Rounding (PRD §2.6)
# ----------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to integer cents, round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_cents(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


# ----------------------------------------------------------------------------
# Datetime parsing
# ----------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.
    Returns None if value is None or unparseable."""
    if value is None or not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------------------
# Input validation helpers (raise ERR_INVALID_REQUEST on failure)
# ----------------------------------------------------------------------------
def require_body(data):
    if not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_str(data, key):
    v = data.get(key)
    if not isinstance(v, str) or v.strip() == "":
        fail(ERR_INVALID_REQUEST, f"{key} is required and must be a non-empty string")
    return v


def require_enum(data, key, allowed):
    v = data.get(key)
    if v not in allowed:
        fail(ERR_INVALID_REQUEST, f"{key} must be one of {sorted(allowed)}")
    return v


def require_int(data, key, minimum=None, maximum=None):
    v = data.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        fail(ERR_INVALID_REQUEST, f"{key} is required and must be an integer")
    if minimum is not None and v < minimum:
        fail(ERR_INVALID_REQUEST, f"{key} must be >= {minimum}")
    if maximum is not None and v > maximum:
        fail(ERR_INVALID_REQUEST, f"{key} must be <= {maximum}")
    return v


def optional_int(data, key, default, minimum=None, maximum=None):
    if key not in data or data.get(key) is None:
        return default
    return require_int(data, key, minimum, maximum)


def require_number(data, key, minimum=None, maximum=None):
    v = data.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail(ERR_INVALID_REQUEST, f"{key} is required and must be a number")
    if minimum is not None and v < minimum:
        fail(ERR_INVALID_REQUEST, f"{key} must be >= {minimum}")
    if maximum is not None and v > maximum:
        fail(ERR_INVALID_REQUEST, f"{key} must be <= {maximum}")
    return v


def optional_number(data, key, default, minimum=None, maximum=None):
    if key not in data or data.get(key) is None:
        return default
    return require_number(data, key, minimum, maximum)


def require_datetime(data, key):
    v = data.get(key)
    dt = parse_dt(v)
    if dt is None:
        fail(ERR_INVALID_REQUEST, f"{key} is required and must be an ISO 8601 datetime")
    return dt


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10, min 1, max 100; offset default 0.
# ----------------------------------------------------------------------------
def parse_pagination(args):
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") is not None and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            fail(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if "offset" in args and args.get("offset") is not None and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            fail(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items must already be sorted. Returns (page, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def sorted_by_creation(items):
    """Default list sort: creation timestamp ascending (PRD §2.3). Uses the
    monotonic _seq for a stable order even within the same millisecond."""
    return sorted(items, key=lambda r: r.get("_seq", 0))
