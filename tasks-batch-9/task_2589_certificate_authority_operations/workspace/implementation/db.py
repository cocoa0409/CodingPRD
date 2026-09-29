"""In-memory data store, logical clock, and record helpers.

The store starts completely empty on every boot: no seeding, no preloaded
entities, no persistence of any kind.
"""

import datetime
import itertools
import uuid

UTC = datetime.timezone.utc

# PRD 2.6: the logical clock starts at this fixed instant on every boot.
CLOCK_EPOCH = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# PRD 2.11: the first certificate ever issued gets serial "1000001".
FIRST_SERIAL = 1000001


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.profiles = {}
        self.subscribers = {}
        self.vettings = {}
        self.authorizations = {}
        self.requests = {}
        self.certificates = {}
        self.partitions = {}
        self.ceremonies = {}
        self.ct_submissions = {}
        self.revocation_requests = {}
        self.crl_publications = {}
        self.incidents = {}
        self.audits = {}
        self.communications = {}
        self.current_utc = CLOCK_EPOCH
        self._seq = itertools.count(1)
        self._serial = itertools.count(FIRST_SERIAL)
        self._token = itertools.count(1)

    # --- clock -----------------------------------------------------------
    def now(self):
        return self.current_utc

    def next_seq(self):
        return next(self._seq)

    def next_serial(self):
        return str(next(self._serial))

    def next_challenge_token(self):
        return "dcv-challenge-%06d" % next(self._token)


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_ts(value):
    """Parse an ISO 8601 timestamp string; return None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def make_record(fields, versioned=True):
    """Create a record dict with the system-managed common fields."""
    now = db.now()
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = now
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and bump version (PRD 2.4)."""
    rec["updated_at"] = db.now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def public(rec):
    """Serialise a record: drop internals, render datetimes."""
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime.datetime):
            out[key] = iso(value)
        else:
            out[key] = value
    return out


def sort_records(records, key=None):
    """Default ordering is created_at ascending (PRD 2.3); insertion order
    breaks ties deterministically."""
    if key is None:
        return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    return sorted(records, key=key)
