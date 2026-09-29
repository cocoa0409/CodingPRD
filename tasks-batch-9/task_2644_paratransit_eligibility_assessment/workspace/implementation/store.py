"""In-memory data store, the logical clock and time helpers.

PRD 2.7: nothing in this system reads wall-clock time.  Before the clock has
ever been set it reads exactly 2026-08-01T00:00:00Z and it never falls back to
the host's real time.

Storage is in-memory only: plain dicts keyed by id.  The store starts EMPTY on
every boot; no entity is ever seeded, preloaded or hardcoded.
"""

import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone, date

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.applicants = {}
        self.applications = {}
        self.verifications = {}
        self.slots = {}
        self.assessments = {}
        self.vehicles = {}
        self.bookings = {}
        self.determinations = {}
        self.trip_conditions = {}
        self.appeals = {}
        self.trip_events = {}
        self.proceedings = {}
        self.referrals = {}
        self.visitor_records = {}
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# identity + timestamps
# --------------------------------------------------------------------------

def new_id():
    """PRD 2.4: server-minted UUID, no type prefix, never supplied by client."""
    return str(uuid.uuid4())


def new_request_id():
    """PRD 2.2: api_request_id starts with req_."""
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now():
    return db.clock


def now_iso():
    return iso(db.clock)


def today():
    return db.clock.astimezone(timezone.utc).date()


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def parse_instant(value):
    """Parse a well-formed ISO 8601 UTC instant.  Returns None when unusable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD).  Returns None when unusable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def date_str(d):
    return None if d is None else d.isoformat()


def date_of(dt):
    """Calendar date of an instant, in UTC."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).date()


# --------------------------------------------------------------------------
# day arithmetic (PRD 2.8)
# --------------------------------------------------------------------------

def elapsed_days(start, end):
    """Whole number of days in the difference, remainder discarded (floor)."""
    if start is None or end is None:
        return 0
    seconds = (end - start).total_seconds()
    return int(seconds // 86400)


def plus_days(d, n):
    return d + timedelta(days=n)


# --------------------------------------------------------------------------
# record bookkeeping
# --------------------------------------------------------------------------

def base_record(with_version=True):
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": db.next_seq()}
    if with_version:
        rec["updated_at"] = now_iso()
        rec["version"] = 1
    return rec


def touch(rec):
    """PRD 2.4: refresh updated_at and increment version by exactly one."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def ordered(records):
    """PRD 2.3 default ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
