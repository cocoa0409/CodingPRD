"""In-memory store, the logical clock, and the per-request mutation tracker.

PRD S2.4: the logical clock reads exactly 2026-08-01T00:00:00Z before any client
sets it and MUST NOT fall back to the host's real time at any point, so every
`created_at` / `updated_at` / `api_request_timestamp` is derived from it.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded — every row is built by a client through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

LOCK = threading.RLock()

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------


def parse_iso(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD S2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def add_days(dt, days):
    """Whole days added to an instant preserve the time-of-day exactly."""
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "sessions",
    "members",
    "drafters",
    "agencies",
    "committees",
    "drafting_requests",
    "statutory_conflicts",
    "bills",
    "committee_referrals",
    "fiscal_note_requests",
    "cost_estimates",
    "amendments",
    "enrolled_bills",
    "technical_corrections",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_iso(DEFAULT_CLOCK_UTC)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_iso(self.clock)


db = Store()


def new_id():
    return str(uuid.uuid4())


def create_row(collection, fields, versioned=True):
    """Insert a fresh row.  `version` starts at 1; `created_at` is the clock."""
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = db.now_iso()
    if versioned:
        row["updated_at"] = db.now_iso()
        row["version"] = 1
    row["_seq"] = db.next_seq()
    row["_new"] = True
    getattr(db, collection)[row["id"]] = row
    return row


def all_rows(collection):
    """Rows of a collection in stable insertion order."""
    return sorted(getattr(db, collection).values(), key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# per-request mutation tracking
#
# PRD S2.5 / S2.10: a mutated row gets `updated_at` refreshed and `version`
# increased by exactly 1 -- once per request, no matter how many individual
# fields of that row the request touched (a referral creation bumps the bill
# once even though it changes both referral_count and legislative_status).
# ---------------------------------------------------------------------------


class _Tracker(object):
    def __init__(self):
        self.dirty = []

    def mark(self, row):
        """Apply the bump immediately -- the response body of the very request
        that mutated the row must already show the new `version` -- but only the
        first time this request touches this row."""
        if row is None:
            return row
        if row.get("_new"):
            return row
        for existing in self.dirty:
            if existing is row:
                return row
        self.dirty.append(row)
        if "version" in row:
            row["version"] = row["version"] + 1
        if "updated_at" in row:
            row["updated_at"] = db.now_iso()
        return row

    def commit(self):
        self.dirty = []


_local = threading.local()


def _clear_new_flags():
    for name in COLLECTIONS:
        for row in getattr(db, name).values():
            if row.get("_new"):
                row["_new"] = False


def begin_request():
    # Rows inserted by the previous request are no longer new, so touching them
    # now must bump their version.
    _clear_new_flags()
    _local.tracker = _Tracker()


def tracker():
    tr = getattr(_local, "tracker", None)
    if tr is None:
        tr = _Tracker()
        _local.tracker = tr
    return tr


def touch(row):
    """Mark a row as mutated by this request."""
    return tracker().mark(row)


def commit():
    tracker().commit()
    _clear_new_flags()


def rollback():
    tracker().dirty = []
    _clear_new_flags()
