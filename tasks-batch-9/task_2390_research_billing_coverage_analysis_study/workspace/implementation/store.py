"""In-memory data store, logical clock and record helpers.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here; every entity is created by the declared API surface.
"""

import datetime as _dt
import random
import string
import uuid

# ---------------------------------------------------------------------------
# Logical clock.  Before any client sets it, it reads exactly
# 2026-08-01T00:00:00Z and it never falls back to wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_EPOCH = _dt.datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=_dt.timezone.utc)

_clock = CLOCK_EPOCH
_seq = 0

# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
studies = {}
analyses = {}
coverage_items = {}
calendars = {}
calendar_visits = {}
routes = {}
subjects = {}
subject_visits = {}
charges = {}
invoices = {}
findings = {}
amendments = {}

_ALL = (
    studies, analyses, coverage_items, calendars, calendar_visits, routes,
    subjects, subject_visits, charges, invoices, findings, amendments,
)


def reset():
    for coll in _ALL:
        coll.clear()
    global _clock, _seq
    _clock = CLOCK_EPOCH
    _seq = 0


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------
def now():
    return _clock


def set_clock(value):
    global _clock
    _clock = value
    return _clock


def today():
    """Date part of the current logical clock as a YYYY-MM-DD string."""
    return _clock.date().isoformat()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def base_record(versioned=True):
    """Common fields.  Write-once records (coverage items, calendar visits and
    visit charge routes) carry only id and created_at - no updated_at, no
    version (PRD 2.4)."""
    rec = {
        "id": new_id(),
        "created_at": now(),
        "_seq": next_seq(),
    }
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Ordinary mutation: refresh updated_at and increment version by one."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def by_created(records):
    """Oldest-created first, with a stable creation-sequence tie-break (the
    logical clock does not advance on its own, so many rows share created_at)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
