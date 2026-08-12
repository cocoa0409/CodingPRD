"""In-memory store, logical clock, id/timestamp/version helpers.

STORAGE IS IN-MEMORY ONLY. Nothing is written to disk, no database, no cache.
NOTHING is seeded: every collection below starts empty on every boot and is only
ever populated through the declared HTTP surface.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone, date

import constants as C

# ---------------------------------------------------------------------------
# Collections — all empty at import time. No seeding, ever.
# ---------------------------------------------------------------------------
COLLECTIONS = [
    "accounts", "children", "allergen_flags", "plans", "skus", "subscriptions",
    "cycles", "cycle_lines", "resize_events", "skip_records", "pause_records",
    "registries", "registry_items", "gift_orders", "credits", "shipments",
    "loyalty_accounts", "points_ledger_entries", "referrals", "refunds",
    "substitution_events",
]


class _DB(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        # credit contributions per cycle: cycle_id -> [{"credit_id":.., "cents":..}]
        self.cycle_credit_contributions = {}
        self._seq = 0
        self.clock_dt = _parse_instant(C.DEFAULT_CLOCK_UTC)
        self.clock_raw = C.DEFAULT_CLOCK_UTC

    def next_seq(self):
        self._seq += 1
        return self._seq


# ---------------------------------------------------------------------------
# Instants / dates
# ---------------------------------------------------------------------------
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?[Zz]$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _parse_instant(value):
    """Parse an ISO 8601 UTC instant that MUST end in Z. Returns naive-UTC datetime."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value)
    if not m:
        return None
    frac = m.group(7) or ""
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)), int(m.group(6)), micro)
    except ValueError:
        return None


def parse_instant(value):
    return _parse_instant(value)


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_instant(dt):
    """Canonical rendering: ISO 8601 UTC with EXACTLY three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# The single in-memory store. Every collection starts EMPTY; nothing is seeded.
db = _DB()


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5). Never falls back to wall-clock time.
# ---------------------------------------------------------------------------
def now():
    return db.clock_dt


def today():
    return db.clock_dt.date()


def set_clock(dt, raw):
    db.clock_dt = dt
    db.clock_raw = raw


def clock_raw():
    return db.clock_raw


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def minus_days(dt, days):
    return dt - timedelta(days=days)


def real_now_iso():
    """Wall-clock, used ONLY for the request-metadata timestamp in the envelope."""
    return fmt_instant(datetime.now(timezone.utc).replace(tzinfo=None))


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_row(full=True):
    """Common fields. `full` == the entity carries updated_at + version too."""
    row = {
        "id": new_id(),
        "created_at": now(),
        "_seq": db.next_seq(),
    }
    if full:
        row["updated_at"] = now()
        row["version"] = 1
    return row


def touch(row):
    """Bump version and updated_at. ALWAYS called BEFORE the row is serialized,
    so a mutation response always reports the post-increment version."""
    if row is None:
        return row
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = now()
    return row


def sort_key(row):
    return (row["created_at"], row["_seq"])


def by_created(rows):
    return sorted(rows, key=sort_key)


def values(coll):
    return list(coll.values())
