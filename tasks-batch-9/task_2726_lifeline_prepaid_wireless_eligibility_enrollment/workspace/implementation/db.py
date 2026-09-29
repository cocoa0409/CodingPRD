"""In-memory data store and logical clock for the Lifeline API.

The store starts completely empty on every boot; nothing is seeded.
All temporal reasoning uses the logical clock, which begins at
2026-08-01T00:00:00Z and moves only via POST /lifeline/_clock/set_current_utc.
"""
import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.providers = {}
        self.addresses = {}
        self.subscribers = {}
        self.eligibility_checks = {}
        self.enrollments = {}
        self.devices = {}
        self.service_transfers = {}
        self.claims = {}
        self.audit_samples = {}
        self.cases = {}
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def base_row():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Every mutation - including a pure derived-counter recompute - refreshes
    updated_at and advances version by exactly one."""
    row["updated_at"] = now()
    row["version"] = row["version"] + 1


def created_key(row):
    """Default collection ordering: created_at ASC. The logical clock can be
    frozen, so a monotonic insertion sequence breaks ties deterministically
    (row id never participates in any ordering)."""
    return (row["created_at"], row["_seq"])


def by_created(rows):
    return sorted(rows, key=created_key)


# ---------------------------------------------------------------- timestamps

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro,
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date_only(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=timezone.utc)
    except ValueError:
        return None


def day_start(dt, plus_days=0):
    """Discard the time-of-day component, add days, stamp 00:00:00.000Z."""
    base = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    return base + timedelta(days=plus_days)


def day_end(dt, plus_days=0):
    """Discard the time-of-day component, add days, stamp 23:59:59.999Z."""
    base = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    return base + timedelta(days=plus_days, hours=23, minutes=59, seconds=59,
                            microseconds=999000)


def date_of(dt):
    return dt.date()


def whole_days_between(later, earlier):
    """Elapsed whole days, truncated toward zero."""
    secs = (later - earlier).total_seconds()
    if secs >= 0:
        return int(secs // 86400)
    return -int((-secs) // 86400)
