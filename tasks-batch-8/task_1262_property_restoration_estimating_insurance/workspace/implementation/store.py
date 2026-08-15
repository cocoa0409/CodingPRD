"""In-memory data store, logical clock, ids, timestamps, rounding.

Storage is process-local only: plain dicts keyed by id. The test harness
restarts the server before every test, which wipes all state. Nothing is
seeded at startup.
"""
import itertools
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

TABLES = [
    "carriers", "price_list_entries", "customers", "policies", "claims",
    "inspections", "moisture_readings", "photos", "estimates",
    "estimate_lines", "supplements", "negotiation_rounds",
    "line_dispositions", "code_upgrades", "work_authorizations",
    "invoices", "payments",
]

DB = {name: {} for name in TABLES}

# Global monotonic insertion sequence (stable ordering / tie-breaks).
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

WA_VALIDITY_DAYS = 30
MOISTURE_WET_MARGIN = 2


def now():
    """Current logical clock instant."""
    return CLOCK


def set_clock(dt):
    global CLOCK
    CLOCK = dt


def wall_now():
    return datetime.now(timezone.utc)


def fmt_clock(dt):
    """Canonical logical-clock rendering: Z suffix, fractional part only when
    the instant carries sub-second precision (millisecond truncation)."""
    if dt.microsecond:
        ms = dt.microsecond // 1000
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ts(dt):
    """Common-field timestamp rendering: always three fractional digits."""
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def fmt_meta_ts(dt):
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_dt(value):
    """Parse an ISO-8601 datetime string. Returns aware datetime or None."""
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


# ---------------------------------------------------------------------------
# Rounding / money
# ---------------------------------------------------------------------------

def dec(value):
    """Exact Decimal for a JSON number (str() round-trip avoids float noise)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value):
    """Round half up to integer cents."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def stamp_new(rec):
    ts = now()
    rec["created_at"] = fmt_ts(ts)
    rec["updated_at"] = fmt_ts(ts)
    rec["version"] = 1
    rec["_seq"] = next_seq()
    rec["_created_instant"] = ts
    return rec


def touch(rec):
    """Refresh updated_at and bump version by exactly 1."""
    rec["updated_at"] = fmt_ts(now())
    rec["version"] += 1
    return rec


def refresh(rec):
    """Refresh updated_at without a version bump."""
    rec["updated_at"] = fmt_ts(now())
    return rec
