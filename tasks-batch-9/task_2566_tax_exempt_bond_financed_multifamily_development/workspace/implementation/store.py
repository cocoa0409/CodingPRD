"""In-memory data store, the logical UTC clock, and shared helpers.

Storage is process memory only.  Nothing is seeded: every row is created by a
client through the declared endpoints.
"""

import itertools
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------

# Startup value of the logical UTC clock (PRD section 2.4).
CLOCK_START_UTC = "2026-08-01T00:00:00.000Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?[Zz]$"
)


def parse_iso(value):
    """Parse an ISO-8601 UTC string with a Z suffix.  Returns None on failure."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def fmt_iso(dt):
    """Format a datetime as ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_iso():
    return fmt_iso(datetime.now(timezone.utc))


def add_years(dt, years):
    """Calendar-year addition, clamping 29 February to 28 February."""
    year = dt.year + int(years)
    month = dt.month
    day = dt.day
    if month == 2 and day == 29:
        leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        if not leap:
            day = 28
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def whole_days(start_dt, end_dt):
    """Whole days in the half-open interval [start, end)."""
    return (end_dt - start_dt).days


# --------------------------------------------------------------------------
# integer / rounding helpers
# --------------------------------------------------------------------------

def floor_div(num, den):
    """Floor of num/den for integer inputs (den must be non-zero)."""
    if den == 0:
        return 0
    return num // den


def round_half_up(num, den):
    """round_half_up(num/den) with exact integer arithmetic."""
    if den == 0:
        return 0
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def ceil_div(num, den):
    if den == 0:
        return 0
    return -((-num) // den)


# --------------------------------------------------------------------------
# request identifiers
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# --------------------------------------------------------------------------
# the store
# --------------------------------------------------------------------------

COLLECTIONS = (
    "developers", "investors", "cap_pools", "projects", "allocations",
    "bond_issues", "draws", "units", "agreements", "cost_certs",
    "credit_allocations", "deliveries", "reports", "inspections",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_iso(CLOCK_START_UTC)
        self.clock_raw = CLOCK_START_UTC
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now_clock():
    """Current logical clock instant as a datetime."""
    return db.clock


def now_clock_iso():
    """Current logical clock instant formatted for storage on a row."""
    return fmt_iso(db.clock)


def new_row(collection, fields):
    """Create a row with the common quartet and insert it into `collection`."""
    row_id = str(uuid.uuid4())
    stamp = wall_now_iso()
    row = {
        "id": row_id,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    collection[row_id] = row
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = wall_now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def by_seq(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))


def public(row):
    """Strip internal bookkeeping keys."""
    return {k: v for k, v in row.items() if not k.startswith("_")}
