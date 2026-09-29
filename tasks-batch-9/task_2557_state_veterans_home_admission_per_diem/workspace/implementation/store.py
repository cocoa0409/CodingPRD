"""In-memory data store, logical clock and shared record helpers.

Storage is process-local and volatile: plain Python dicts keyed by record id.
Nothing is seeded at import time or at boot -- every entity is created through
the declared API surface.
"""
import re
import uuid
from datetime import date, datetime, timedelta

# PRD 2.5: before any client sets it, the logical clock reads exactly this
# instant, and it never falls back to real wall-clock time.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00.000Z"

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def parse_iso_datetime(value):
    """Parse an ISO-8601 instant into a naive UTC datetime, or return None."""
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
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
        dt = dt - sign * offset
    return dt


def format_datetime(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def format_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def valid_month(value):
    return isinstance(value, str) and bool(MONTH_RE.match(value))


def month_of_date(d):
    return "%04d-%02d" % (d.year, d.month)


def month_bounds(month):
    """(first_day, last_day) as date objects for a YYYY-MM string."""
    year = int(month[0:4])
    mon = int(month[5:7])
    first = date(year, mon, 1)
    if mon == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, mon + 1, 1) - timedelta(days=1)
    return first, last


def days_in_month(month):
    first, last = month_bounds(month)
    return (last - first).days + 1


def days_between(start, end):
    """Whole calendar days from start to end (end - start)."""
    return (end - start).days


def date_in_month(d, month):
    return month_of_date(d) == month


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.homes = {}
        self.care_units = {}
        self.applicants = {}
        self.waitlist_entries = {}
        self.assessments = {}
        self.residents = {}
        self.income_records = {}
        self.determinations = {}
        self.care_plans = {}
        self.census_days = {}
        self.claims = {}
        self.transactions = {}
        self._seq = 0
        self.clock = parse_iso_datetime(CLOCK_DEFAULT_ISO)

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# ---------------------------------------------------------------- clock ----
def now_iso():
    return format_datetime(store.clock)


def clock_date():
    return store.clock.date()


def clock_month():
    return month_of_date(clock_date())


def set_clock(dt):
    store.clock = dt


# --------------------------------------------------------------- records ----
def new_record(versioned=True):
    stamp = now_iso()
    rec = {"id": str(uuid.uuid4()), "created_at": stamp, "_seq": store.next_seq()}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def _touched_set():
    try:
        from flask import g, has_request_context
        if has_request_context():
            if not hasattr(g, "_touched_records"):
                g._touched_records = set()
            return g._touched_records
    except Exception:
        pass
    return None


def touch_once(rec):
    """Increment version at most once per request for this record."""
    seen = _touched_set()
    if seen is None:
        touch(rec)
        return
    if rec["id"] in seen:
        return
    seen.add(rec["id"])
    touch(rec)


def order_key(rec):
    """Stable (created_at, insertion-sequence) ordering key."""
    return (rec["created_at"], rec["_seq"])


def by_created(rows, reverse=False):
    return sorted(rows, key=order_key, reverse=reverse)
