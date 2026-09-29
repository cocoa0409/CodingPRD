"""In-memory data store, logical clock and record helpers.

The store is EMPTY on every boot. Nothing is seeded, preloaded or hardcoded:
every entity is created by an API call.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD §2.4 — the logical UTC clock starts at exactly 2026-08-01T00:00:00Z and the
# server never reads the wall clock.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        self.jurisdictions = {}
        self.agencies = {}
        self.cells = {}
        self.roads = {}
        self.points = {}
        self.requests = {}
        self.boundaries = {}
        self.assignments = {}
        self.reports = {}
        self.defects = {}
        self.packages = {}
        self.package_records = {}
        self.cases = {}
        self.proposals = {}

    def now(self):
        return self.clock

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# datetime helpers
# ---------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO 8601 datetime; return a tz-aware UTC datetime truncated to ms.

    Returns None when the value is not a valid ISO 8601 datetime.
    """
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    try:
        if tz in (None, "Z", "z"):
            dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
        else:
            sign = 1 if tz[0] == "+" else -1
            body = tz[1:].replace(":", "")
            offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4])) * sign
            dt = datetime(year, month, day, hour, minute, second, micro,
                          tzinfo=timezone(offset)).astimezone(timezone.utc)
    except ValueError:
        return None
    # millisecond resolution (PRD §2.4)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def fmt_dt(dt):
    """ISO 8601 UTC with EXACTLY three fractional digits and trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


def base_record():
    """id / created_at / updated_at / version common fields (PRD §2.5)."""
    now = db.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def append_only_record():
    """DiscrepancyProposal carries only id and created_at (PRD §2.5)."""
    return {
        "id": new_id(),
        "created_at": db.now(),
        "_seq": db.next_seq(),
    }


def sorted_rows(rows):
    """Default sort: created_at ASC (never by id); insertion order breaks ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def touch(record):
    """Bare mutation stamp: version + 1 and updated_at at the logical instant."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = db.now()
