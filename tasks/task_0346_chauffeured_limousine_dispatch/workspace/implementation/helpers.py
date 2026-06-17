"""Shared helpers: datetime parsing, serialization, pagination, body validation."""
import math
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from errors import ERR_INVALID_REQUEST, err

# Internal bookkeeping keys that must never be serialized out to clients.
_PRIVATE_KEYS = {"_seq"}


def serialize(rec):
    """Strip internal keys from a stored record for the response body."""
    return {k: v for k, v in rec.items() if k not in _PRIVATE_KEYS}


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 UTC datetime. Raises ERR_INVALID_REQUEST on bad shape."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 string")
    raw = value.strip()
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_dt(dt):
    """Format a datetime back to ISO 8601 UTC with a trailing 'Z'.

    Emits second precision when there is no fractional component, else
    millisecond precision — matching the shapes the test fixtures use.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def floor_minutes(later, earlier):
    """Whole minutes between two datetimes, discarding the partial minute (floor).

    PRD §2.7: total elapsed seconds floored to whole minutes. Goes negative when
    `later` precedes `earlier`.
    """
    total_seconds = (later - earlier).total_seconds()
    return math.floor(total_seconds / 60)


def round_half_up(value):
    """Round a numeric value half up to the nearest whole integer (PRD §2.7)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_hours(hours):
    """Charter hours rounded up to the next whole hour (PRD §2.7)."""
    return math.ceil(hours)


def require_fields(body, fields):
    """Ensure required fields are present (not None). ERR_INVALID_REQUEST otherwise."""
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    for f in fields:
        if body.get(f) is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a number")
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    return value


def as_str(value, field):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a string")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return value


def get_pagination(args):
    """Parse limit/offset query params (PRD §2.3).

    limit defaults 10, min 1, max 100. offset defaults 0. Out-of-shape values
    are rejected with ERR_INVALID_REQUEST.
    """
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be zero or greater")
    return limit, offset


def paginate(items, limit, offset):
    """Apply limit/offset and produce pagination meta (PRD §2.3)."""
    total = len(items)
    window = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, pagination


def sort_by_created(items):
    """Sort a list of records by created_at ascending (PRD §2.3).

    Uses the monotonic _seq as a stable tiebreak so equal timestamps keep
    insertion order.
    """
    return sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
