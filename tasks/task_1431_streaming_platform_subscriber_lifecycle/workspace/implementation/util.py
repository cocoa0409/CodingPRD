"""Shared helpers: UUIDs, timestamps, common fields, money math."""
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db


def new_uuid():
    return str(uuid.uuid4())


def now_iso():
    return format_ts(db.get_now())


def format_ts(dt):
    """ISO 8601 UTC with 3 fractional digits, e.g. 2025-05-24T10:30:00.123Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse ISO 8601 to aware datetime. Accepts trailing Z."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    v = s
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_cents(value):
    """Round a Decimal/float to 0 places, ROUND_HALF_UP, return int cents."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def stamp_new(entity):
    """Set created_at/updated_at/version on a new entity."""
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and increment version on modification (PRD §2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity


def whole_days(later, earlier):
    """Whole days between two datetimes, floor."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def add_months(dt, months):
    """Add N months (approximated as 30-day months per PRD nominal period)."""
    return dt + timedelta(days=30 * months)
