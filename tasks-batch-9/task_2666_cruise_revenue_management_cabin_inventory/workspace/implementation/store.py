"""In-memory data store, logical clock and row helpers.

Every byte of state lives in module-level dicts and vanishes with the process.
NOTHING is seeded here: every entity is created by a declared endpoint.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# Logical clock (PRD 2.4). Before any client sets it, it reads exactly
# 2026-08-01T00:00:00Z. Real wall-clock time is never consulted for business
# logic.
# --------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def now_dt():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt.astimezone(timezone.utc)


def reset_clock():
    _clock["now"] = CLOCK_EPOCH


# --------------------------------------------------------------------------
# Timestamp formatting / parsing: ISO 8601 UTC with exactly 3 fractional digits
# --------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso():
    return iso(now_dt())


def add_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Rounding discipline (PRD 2.6): round half up, away from zero on a tie.
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu_int(value):
    """Round half up to a whole unit (cent), returning an int."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to exactly 2 decimals, returning a float."""
    return float(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def days_to_sail(embark_dt, at_dt):
    """floor((embark - at) / 86400 seconds). A partial day never counts.

    Exact integer arithmetic: 47 hours before departure is 1 day to sail, and
    the floor runs toward minus infinity once the ship has left.
    """
    delta = embark_dt - at_dt
    total_us = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    return total_us // (86400 * 1000000)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------
sailings = {}
cabin_categories = {}
sailing_inventories = {}
fare_rules = {}
promotions = {}
group_blocks = {}
guests = {}
bookings = {}
payment_events = {}
upgrade_bids = {}
itinerary_changes = {}

TABLES = (
    sailings, cabin_categories, sailing_inventories, fare_rules, promotions,
    group_blocks, guests, bookings, payment_events, upgrade_bids,
    itinerary_changes,
)


def new_id():
    return str(uuid.uuid4())


def stamp_new(row, versioned=True):
    """Attach identity + system timestamps to a brand-new row."""
    row["id"] = new_id()
    row["created_at"] = now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] = row["version"] + 1
    return row


def apply_changes(row, changes, bump=True):
    """Write derived values; bump version/updated_at only when something moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed and bump:
        touch(row)
    return changed


def values(table):
    """Rows in insertion order (created_at order for a monotone clock)."""
    return list(table.values())
