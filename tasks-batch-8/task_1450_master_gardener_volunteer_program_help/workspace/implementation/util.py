"""Shared utilities: ids, timestamps, decimal quarter-hour math, date parsing."""

import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db


def new_id():
    return str(uuid.uuid4())


def now_iso3():
    """System-managed timestamp stamp. Per PRD §2.5 the server never falls
    back to wall-clock time: created_at/updated_at read the logical clock,
    rendered at second precision (PRD §2.7: timestamps are compared at
    second precision on ISO 8601 UTC values)."""
    return db.clock_state["current_utc"]


def touch(obj):
    """Refresh updated_at and increment version on a mutated resource."""
    obj["updated_at"] = now_iso3()
    obj["version"] = obj.get("version", 1) + 1


def new_resource(fields):
    """Create a resource dict with common system fields."""
    ts = now_iso3()
    obj = dict(fields)
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


# ---------- logical clock ----------

def logical_clock():
    """Return the current logical clock as an aware datetime."""
    return parse_dt(db.clock_state["current_utc"])


def logical_clock_iso():
    return db.clock_state["current_utc"]


# ---------- parsing ----------

def parse_dt(s):
    """Parse ISO 8601 datetime, tolerant of trailing Z and fractional digits."""
    if isinstance(s, datetime):
        return s
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with second precision and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(s):
    """Parse ISO 8601 date (YYYY-MM-DD) to a date object."""
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    return date.fromisoformat(s.strip())


def is_iso_datetime(s):
    try:
        parse_dt(s)
        return True
    except Exception:
        return False


def is_iso_date(s):
    try:
        parse_date(s)
        return True
    except Exception:
        return False


# ---------- decimal math ----------

def D(v):
    """Coerce to Decimal without float contamination."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, str):
        return Decimal(v)
    return Decimal(str(v))


def round_half_up(d, places):
    q = Decimal(1).scaleb(-places)
    return D(d).quantize(q, rounding=ROUND_HALF_UP)


def round_quarter(d):
    """Round half-up to nearest 0.25."""
    return (D(d) * 4).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / Decimal(4)


def is_multiple_quarter(v):
    try:
        d = D(v)
    except Exception:
        return False
    return (d * 4) == (d * 4).to_integral_value()


def hours_num(d):
    """Convert a Decimal hour total to a float with 2dp rounding for JSON output."""
    return float(round_half_up(d, 2))


# ---------- pagination ----------

def paginate(items, args, on_invalid=None):
    """Apply limit/offset with scaffold defaults: limit default 10, min 1, max 100, offset default 0."""
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            if on_invalid:
                on_invalid()
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            if on_invalid:
                on_invalid()
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def sort_created(items):
    # Stable sort on created_at only: under the deterministic logical clock
    # many resources share a created_at instant; ties must resolve to
    # creation (insertion) order, which dict value iteration preserves —
    # never to random UUIDs.
    return sorted(items, key=lambda x: x.get("created_at", ""))
