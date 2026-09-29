"""In-memory data store, logical clock and row bookkeeping.

The store is EMPTY on every boot.  Nothing is seeded, preloaded or hardcoded:
every entity the tests need is created through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# PRD 2.4: before the clock has ever been set it reads exactly this instant and
# never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.stakeholders = {}
        self.sites = {}
        self.applications = {}
        self.assets = {}
        self.observations = {}
        self.dependency_edges = {}
        self.recovery_groups = {}
        self.runbooks = {}
        self.runbook_steps = {}
        self.exercises = {}
        self.scope_items = {}
        self.step_executions = {}
        self.findings = {}
        self.evidence_packages = {}
        self.clock = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def now():
    """The current logical clock instant."""
    return db.clock


def new_id():
    # PRD 2.5: a server-minted UUID carrying no type prefix.
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# timestamps
# --------------------------------------------------------------------------- #

def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 UTC datetime.  Returns None when malformed."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def real_now_iso():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


# --------------------------------------------------------------------------- #
# row bookkeeping: common fields, mutation tracking
# --------------------------------------------------------------------------- #

def _touched_set():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = set()
    return g._touched_rows


def new_row(common_fields=True):
    """Build a row carrying the standard server-managed fields (PRD 2.5)."""
    row = {"id": new_id(), "created_at": now()}
    if common_fields:
        row["updated_at"] = now()
        row["version"] = 1
    row["_seq"] = db.next_seq()
    # A row created inside this request must not also be "touched" by the
    # derived-field recomputations that the same request performs; it already
    # carries version 1.
    _touched_set().add(row["id"])
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version, once per request.

    PRD 2.5: derived fields count as mutations.  PRD 2.10 / the endpoint side
    effect tables express every ripple as "increments <row>.version by 1" for
    the request as a whole, so a row is bumped at most once per request.
    """
    if row is None:
        return
    touched = _touched_set()
    if row["id"] in touched:
        # still refresh updated_at so the latest logical instant is visible
        if "updated_at" in row:
            row["updated_at"] = now()
        return
    touched.add(row["id"])
    if "updated_at" in row:
        row["updated_at"] = now()
    if "version" in row:
        row["version"] = row["version"] + 1


def sort_key(row):
    """Deterministic (created_at, insertion-sequence) ordering key."""
    return (row["created_at"], row["_seq"])
