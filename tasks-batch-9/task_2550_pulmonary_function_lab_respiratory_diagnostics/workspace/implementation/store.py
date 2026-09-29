"""In-memory data store, logical clock and record helpers.

Everything lives in plain Python dicts keyed by id. Nothing is persisted and
nothing is seeded: the store is empty on every boot.
"""
import itertools
import re
import uuid
from datetime import datetime, date, timedelta, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_EPOCH
        self.devices = {}
        self.quality_events = {}
        self.staff = {}
        self.patients = {}
        self.equations = {}
        self.lots = {}
        self.orders = {}
        self.holds = {}
        self.sessions = {}
        self.maneuvers = {}
        self.runs = {}
        self.reports = {}
        self.custody_events = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def now(self):
        return self.clock


db = Store()


# ---------------------------------------------------------------- time helpers

def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1000000))
    tzs = m.group(8)
    offset = timedelta(0)
    if tzs and tzs not in ("Z", "z"):
        sign = 1 if tzs[0] == "+" else -1
        body = tzs[1:].replace(":", "")
        offset = sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    try:
        dt = datetime(year, month, day, hour, minute, second, micro,
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt - offset


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def iso_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def day_start(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def current_date():
    return db.clock.date()


# -------------------------------------------------------------- record helpers

def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    """Attach the common system fields to a versioned record."""
    now = iso(db.clock)
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def stamp_event(rec):
    """Attach the reduced system field set to an append-only event record."""
    rec["id"] = new_id()
    rec["created_at"] = iso(db.clock)
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at and bump version by exactly one."""
    if rec is None:
        return None
    rec["updated_at"] = iso(db.clock)
    rec["version"] = int(rec.get("version") or 0) + 1
    return rec


def public(rec, extra=None):
    """Strip internal keys; optionally merge computed fields."""
    if rec is None:
        return None
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = value
    if extra:
        out.update(extra)
    return out


def sort_key(rec):
    """Default collation: created_at ascending, insertion order as tiebreak."""
    return (rec.get("created_at") or "", rec.get("_seq") or 0)


def by_created(records):
    return sorted(records, key=sort_key)
