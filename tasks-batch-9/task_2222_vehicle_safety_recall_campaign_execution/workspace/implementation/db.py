"""In-memory data store, logical clock and record helpers.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  Every entity is created through the declared API surface.
"""
import itertools
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import g

UTC = timezone.utc

# PRD 2.4 - the logical clock's startup default.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.campaigns = {}
        self.population_rules = {}
        self.vehicles = {}
        self.affected_vehicles = {}
        self.waves = {}
        self.dealers = {}
        self.remedy_parts = {}
        self.allocations = {}
        self.labor_operations = {}
        self.repair_claims = {}
        self.reimbursements = {}
        self.outreach_attempts = {}
        self.filings = {}
        self.clock = CLOCK_DEFAULT
        self.seq = itertools.count(1)


store = Store()


# --------------------------------------------------------------------------
# instant / date formatting and parsing
# --------------------------------------------------------------------------
def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns None when unparsable."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mm = (int(m.group(i)) for i in range(1, 6))
    ss = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzs = m.group(8)
    try:
        dt = datetime(y, mo, d, hh, mm, ss, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tzs and tzs not in ("Z", "z"):
        sign = 1 if tzs[0] == "+" else -1
        body = tzs[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Returns None when unparsable."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def now_wall():
    return datetime.now(UTC)


def clock_now():
    return store.clock


def clock_date():
    return store.clock.astimezone(UTC).date()


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    ts = fmt_instant(now_wall())
    rec = {"id": new_id(), "created_at": ts, "_seq": next(store.seq)}
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at/version once per record per request (PRD 2.5)."""
    if rec is None:
        return
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is not None:
        if rec["id"] in seen:
            rec["updated_at"] = fmt_instant(now_wall())
            return
        seen.add(rec["id"])
    rec["updated_at"] = fmt_instant(now_wall())
    if "version" in rec:
        rec["version"] = rec["version"] + 1


def order_key(rec):
    return (rec["created_at"], rec["_seq"])


def sorted_records(records):
    return sorted(records, key=order_key)
