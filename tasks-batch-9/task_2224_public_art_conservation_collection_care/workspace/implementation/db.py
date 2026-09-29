"""In-memory data store and the logical conservation clock (PRD 2.6).

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  Every record any caller needs is built through the public API.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock reads exactly this instant until it is moved (PRD 2.6).
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.artists = {}
        self.sites = {}
        self.artworks = {}
        self.protocols = {}
        self.visits = {}
        self.assessments = {}
        self.conservators = {}
        self.proposals = {}
        self.consultations = {}
        self.notices = {}
        self.cases = {}
        self.pools = {}
        self.allocations = {}
        self.incidents = {}
        self.clock = CLOCK_ORIGIN
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# clock helpers
# --------------------------------------------------------------------------

def now():
    """The logical clock. Nothing in this system reads the machine wall clock."""
    return db.clock


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_now():
    return fmt_instant(now())


def fmt_date(dt):
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


def today_iso():
    return fmt_date(now())


def parse_instant(value):
    """Parse an ISO 8601 instant; returns an aware UTC datetime or raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text[-1] in ("z", "Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date (a leading YYYY-MM-DD is enough); returns a date."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if len(text) < 10:
        raise ValueError("too short")
    return datetime.fromisoformat(text[:10]).date()


def plus_days(dt, days):
    return dt + timedelta(days=int(days))


def date_plus_days(d, days):
    return d + timedelta(days=int(days))


# --------------------------------------------------------------------------
# record helpers -- common properties (PRD 2.5)
# --------------------------------------------------------------------------

def _touched_set():
    from flask import g
    bucket = getattr(g, "_touched_records", None)
    if bucket is None:
        bucket = set()
        g._touched_records = bucket
    return bucket


def create_record(store, fields):
    stamp = iso_now()
    rec = {"id": str(uuid.uuid4())}
    rec.update(fields)
    rec["created_at"] = stamp
    rec["updated_at"] = stamp
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    store[rec["id"]] = rec
    # A freshly created record is already at version 1 for this request; any
    # in-request roll-up must not push it to 2.
    _touched_set().add(rec["id"])
    return rec


def touch(rec):
    """Refresh updated_at and increment version exactly once per request."""
    if rec is None:
        return
    seen = _touched_set()
    if rec["id"] in seen:
        return
    seen.add(rec["id"])
    rec["updated_at"] = iso_now()
    rec["version"] = int(rec.get("version", 0)) + 1


def ordered(records):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(records, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
