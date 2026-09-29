"""In-memory data store, logical clock and row helpers.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded — every row is created through the declared API surface.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK_STR = "2026-08-01T00:00:00Z"

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6})\d*)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_datetime(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
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
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz_body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz_body[:2]), minutes=int(tz_body[2:4]))
        dt = dt - sign * offset
    return dt


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date, or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc).date()
    except ValueError:
        return None


def fmt_datetime(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.agents = {}
        self.inspectors = {}
        self.pools = {}
        self.accounts = {}
        self.policies = {}
        self.scheduled_items = {}
        self.livestock_groups = {}
        self.liability_exposures = {}
        self.endorsements = {}
        self.labor_profiles = {}
        self.inspections = {}
        self.recommendations = {}
        self.reservations = {}
        self.premium_txns = {}
        self.clock = parse_datetime(DEFAULT_CLOCK_STR)
        self.clock_raw = DEFAULT_CLOCK_STR
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


store = Store()


def now_dt():
    return store.clock


def now_str():
    return fmt_datetime(store.clock)


def today():
    return store.clock.astimezone(timezone.utc).date()


def new_row(**fields):
    stamp = now_str()
    row = {
        "id": str(uuid.uuid4()),
        "_seq": store.next_seq(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    return row


def touch(row):
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now_str()
    return row


def by_created(rows):
    """created_at ascending, insertion order as the stable tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
