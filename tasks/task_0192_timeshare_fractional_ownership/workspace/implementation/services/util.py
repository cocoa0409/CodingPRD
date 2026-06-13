"""Shared utilities: serialization, time/window math, validation primitives."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

import errors

# Fields that are internal-only and must never be serialized to clients.
_INTERNAL_FIELDS = {"_seq"}


def serialize(obj, computed=None):
    """Return a public copy of a stored entity, stripping internal fields and
    merging any computed fields."""
    out = {k: v for k, v in obj.items() if k not in _INTERNAL_FIELDS}
    if computed:
        out.update(computed)
    return out


# ---------------------------------------------------------------------------
# Time / window helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO 8601 UTC timestamp into a timezone-aware datetime."""
    if s is None:
        return None
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def whole_days_between(earlier, later):
    """Whole days from `earlier` to `later` (later - earlier), truncated toward zero."""
    delta = later - earlier
    return delta.days  # timedelta.days floors toward negative infinity; fine for our >=180 checks


def use_year_start(use_year):
    """Start instant of a use-year: Jan 1 00:00:00 UTC of that year."""
    return datetime(int(use_year), 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Rounding helpers (operate on integer-producing rules)
# ---------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div_value(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def ceil_value(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Body validation primitives
# ---------------------------------------------------------------------------
def require_body(data):
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def require_fields(data, fields):
    for f in fields:
        if data.get(f) is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return v


def require_int(data, field, minimum=None, positive=False):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    if positive and v <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be > 0." % field)
    if minimum is not None and v < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s." % (field, minimum))
    return v


def require_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise errors.err(
            errors.ERR_INVALID_REQUEST,
            "Field %s must be one of %s." % (field, sorted(allowed)),
        )
    return v
