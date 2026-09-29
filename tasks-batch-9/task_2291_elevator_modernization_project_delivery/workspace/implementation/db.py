"""In-memory data store, logical clock and common-field helpers.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or hardcoded here: every row a test needs is created through the declared API
surface.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock reads exactly this before any request has moved it and it
# never falls back to the host's real clock (PRD 2.4).
DEFAULT_CLOCK_STR = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_lock = threading.Lock()
_last_wall = {"dt": None}


def wall_now():
    """Strictly monotonic wall-clock instant (millisecond resolution).

    created_at / updated_at record when a row was inserted / last mutated.  We
    force strict monotonicity so that a mutation always produces a visibly
    different updated_at string.
    """
    with _lock:
        raw = datetime.now(timezone.utc)
        now = raw.replace(microsecond=(raw.microsecond // 1000) * 1000)
        prev = _last_wall["dt"]
        if prev is not None and now <= prev:
            now = prev + timedelta(milliseconds=1)
        _last_wall["dt"] = now
        return now


def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    """ISO 8601 UTC for domain instants.

    The house rendering for every timestamp this API emits is ISO 8601 UTC with
    exactly three fractional digits (PRD 2.2, PRD 2.4).
    """
    return fmt_ms(dt)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.jurisdictions = {}
        self.projects = {}
        self.groups = {}
        self.cars = {}
        self.surveys = {}
        self.scope_options = {}
        self.code_triggers = {}
        self.procurement_orders = {}
        self.staging_reservations = {}
        self.outage_windows = {}
        self.inspections = {}
        self.warranty_transitions = {}
        self.contracts = {}
        self.clock_dt = DEFAULT_CLOCK_DT
        self.clock_str = DEFAULT_CLOCK_STR
        self._seq = itertools.count(1)


db = Store()


def clock_dt():
    return db.clock_dt


def clock_str():
    return db.clock_str


def new_row(**fields):
    # Audit stamps read the logical clock: time in this system is not
    # wall-clock time and never falls back to the host's real clock (PRD 2.4).
    now = db.clock_dt
    row = {
        "id": str(uuid.uuid4()),
        "created_at": fmt_ms(now),
        "updated_at": fmt_ms(now),
        "version": 1,
        "_seq": next(db._seq),
    }
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at and bump version by exactly 1."""
    row["updated_at"] = fmt_ms(db.clock_dt)
    row["version"] = row["version"] + 1


def ordered(rows):
    """Collections are ordered by created_at ascending, stably."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
