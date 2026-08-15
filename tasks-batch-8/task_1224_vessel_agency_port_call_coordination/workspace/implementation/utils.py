"""Shared helpers: datetimes, decimal rounding, entities, pagination."""
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db


# ---------------------------------------------------------------- datetimes
def parse_dt(value):
    """Parse an ISO-8601 datetime. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Domain datetime -> ISO 8601 UTC. Seconds when whole, else millis."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        ms = dt.microsecond // 1000
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ts(dt):
    """System timestamp -> ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


# ---------------------------------------------------------------- decimals
def dec(value):
    return Decimal(str(value))


def rhu_cents(value):
    """Round a Decimal to integer cents, half-up (ties away from zero)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_pct_2dp(value):
    """Round a Decimal to 2 decimal places, half-up; returned as float."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def days_between(start, end):
    """ceil(hours/24) with a minimum of 1 day."""
    seconds = (end - start).total_seconds()
    return max(1, int(math.ceil(seconds / 86400.0)))


# ---------------------------------------------------------------- entities
def new_entity(store_name, fields):
    """Create and store an entity with common system fields."""
    ent = dict(fields)
    ent["id"] = db.new_id()
    ts = db.now()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = db.next_seq()
    db.STORES[store_name][ent["id"]] = ent
    return ent


def touch(ent):
    """Record a modification: refresh updated_at and bump version."""
    ent["updated_at"] = db.now()
    ent["version"] += 1


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and not (isinstance(value, float) and (value != value)))


# ---------------------------------------------------------------- pagination
def pagination_args(args):
    """limit: default 10, clamped to [1, 100]; offset: default 0, floored at 0."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more


def sort_created(items):
    """created_at ascending, stable by insertion sequence."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
