"""In-memory data store.

The store is process-local and starts completely empty on every boot: no seeding,
no preloading, no persistence of any kind.  Every record any caller sees was
created by a caller through the declared API surface.

PRD 2.6 -- the logical clock: the server never reads wall-clock time for business
reasoning.  `DB.clock` is the single source of "now" for every temporal rule and
is only ever moved by POST /_clock/set_current_utc.
"""

import threading
import uuid
from datetime import datetime

from flask import g

from util import UTC

# The logical clock has to start somewhere before any caller sets it.  This is a
# clock reading, not entity data.
_INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        # One process-wide non-reentrant-safe lock.  Handlers take it exactly
        # once at the request boundary and never acquire any other lock, so it
        # cannot deadlock.
        self.lock = threading.RLock()
        self.clock = _INITIAL_CLOCK
        self._seq = 0
        self.programs = {}
        self.items = {}
        self.forms = {}
        self.candidates = {}
        self.applications = {}
        self.sessions = {}
        self.registrations = {}
        self.incidents = {}
        self.certificants = {}
        self.cycles = {}
        self.activities = {}
        self.cases = {}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


DB = Store()


def new_record(**fields):
    """Create a record carrying the four common fields from PRD 2.4."""
    stamp = DB.now()
    record = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    record.update(fields)
    return record


def _touched():
    marks = getattr(g, "_touched_ids", None)
    if marks is None:
        marks = set()
        g._touched_ids = marks
    return marks


def touch(record):
    """Refresh updated_at and bump version by exactly one for this request.

    PRD 2.4: version increments by 1 on every mutation of that record, including
    mutations reached indirectly through a cascade.  A record mutated several
    times while serving one request still advances by exactly one.
    """
    marks = _touched()
    if record["id"] in marks:
        record["updated_at"] = DB.now()
        return
    marks.add(record["id"])
    record["updated_at"] = DB.now()
    record["version"] += 1


def mark_created(record):
    """A freshly created record must not additionally be version-bumped."""
    _touched().add(record["id"])


def ordered(values):
    """PRD 2.3 default sort: created_at ascending (stable by creation order)."""
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))
