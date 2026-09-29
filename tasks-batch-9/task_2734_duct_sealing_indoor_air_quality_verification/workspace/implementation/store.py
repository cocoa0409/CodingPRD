"""In-memory data store, logical clock and shared record helpers.

Storage is process-local Python dicts only.  The store starts EMPTY on every
boot: no entity is ever seeded, preloaded or hardcoded here.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Startup default of the logical clock (PRD section 2.4).
DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "utility_programs",
    "technicians",
    "projects",
    "duct_systems",
    "leakage_tests",
    "seal_jobs",
    "leakage_samples",
    "combustion_tests",
    "verification_reports",
    "rebate_claims",
    "comfort_complaints",
    "airflow_readings",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK_UTC
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def rows(self, name):
        """All rows of a collection in stable insertion order."""
        return list(getattr(self, name).values())


db = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None when invalid."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    txt = raw
    if txt.endswith(("Z", "z")):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso():
    return iso(db.clock)


def clock():
    return db.clock


def plus_days(dt, days):
    return dt + timedelta(days=days)


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def new_record(versioned=True):
    """Fresh common fields (PRD section 2.4).

    ``_seq`` is a private monotone insertion counter.  It is never serialised;
    it exists so that "greatest created_at" tie-breaks and "created strictly
    after" comparisons stay well defined while the logical clock is frozen.
    """
    stamp = now_iso()
    rec = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version by exactly 1."""
    if "version" in rec:
        rec["updated_at"] = now_iso()
        rec["version"] = rec["version"] + 1
    return rec


def order_key(rec):
    return (rec.get("created_at") or "", rec.get("_seq") or 0)


def by_created(rows):
    return sorted(rows, key=order_key)


def latest(rows):
    """The row with the greatest created_at (tie-break: insertion order)."""
    best = None
    for row in rows:
        if best is None or order_key(row) > order_key(best):
            best = row
    return best


ZERO2 = Decimal("0.00")
