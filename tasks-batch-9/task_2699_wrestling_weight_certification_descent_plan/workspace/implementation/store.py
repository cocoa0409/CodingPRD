"""In-memory store, logical clock and row helpers.

Storage is process-local Python dictionaries only.  Nothing is written to
disk, no database file is opened, and the store starts completely empty on
every boot -- the test harness relaunches the server before each test and
builds all state through the declared endpoints.
"""

import re
import uuid
from datetime import datetime, timezone, timedelta, date

# PRD 2.4: the logical clock's startup default is exactly this instant and it
# never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "seasons",
    "teams",
    "assessors",
    "wrestlers",
    "assessments",
    "appeals",
    "plans",
    "milestones",
    "events",
    "entries",
    "weighins",
    "checks",
    "growth",
    "flags",
    "audits",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self.seq = 0


DB = Store()


def next_seq():
    DB.seq += 1
    return DB.seq


# --------------------------------------------------------------------------
# time formatting / parsing
# --------------------------------------------------------------------------

def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def fmt_date(value):
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def clock_dt():
    return DB.clock


def clock_iso():
    return fmt_dt(DB.clock)


def clock_date():
    return DB.clock.astimezone(timezone.utc).date()


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if tz[0] == "+" else -1
    tz = tz[1:].replace(":", "")
    offset = timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
    return (naive - sign * offset).replace(tzinfo=timezone.utc)


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def day_start(d):
    """Midnight UTC on the given calendar date, as an aware datetime."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def new_row(common=True):
    """Mint a fresh row skeleton.

    ``common`` is False for the three append-only entities (WeighIn,
    EligibilityCheck, GrowthAllowance) which carry neither ``updated_at``
    nor ``version``.
    """
    row = {
        "id": str(uuid.uuid4()),
        "_seq": next_seq(),
        "created_at": clock_iso(),
    }
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = clock_iso()
    row["version"] = int(row.get("version") or 1) + 1


def sort_created(rows):
    """Default list ordering: created_at ASC, insertion sequence as tie-break."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))


def values(collection):
    return list(collection.values())
