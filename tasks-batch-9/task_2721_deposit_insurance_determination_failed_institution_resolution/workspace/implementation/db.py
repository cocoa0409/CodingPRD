"""In-memory data store, logical clock and the shared version/audit bookkeeping.

Storage is process-local Python dictionaries keyed by resource id.  Nothing is
seeded at import time or at boot: every row in every collection is created by a
client call to a declared endpoint.
"""

from flask import g

from util import CLOCK_EPOCH_ISO, format_iso, new_uuid, parse_iso


class Store:
    """Every collection in the API, plus the logical clock."""

    def __init__(self):
        self.institutions = {}
        self.submissions = {}
        self.depositors = {}
        self.accounts = {}
        self.interests = {}
        self.determinations = {}
        self.certificates = {}
        self.bidders = {}
        self.bids = {}
        self.reopenings = {}
        self.distributions = {}
        self.clock = parse_iso(CLOCK_EPOCH_ISO)
        self._seq = 0

    def next_seq(self):
        """Monotonic insertion counter, used only to keep sorts stable when two
        rows share a logical-clock ``created_at``."""
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return format_iso(self.clock)


db = Store()


def _touched():
    """Per-request set of resource ids already version-bumped by this request."""
    try:
        seen = g.get("_touched_ids", None)
    except RuntimeError:  # pragma: no cover - outside a request context
        return None
    if seen is None:
        seen = set()
        g._touched_ids = seen
    return seen


def new_row(extra=None):
    """Create the common audit fields of a versioned resource (PRD 2.4)."""
    stamp = db.now_iso()
    row = {
        "id": new_uuid(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    seen = _touched()
    if seen is not None:
        seen.add(id(row))
    return row


def new_immutable_row(extra=None):
    """An OwnershipInterest carries only ``id`` and ``created_at`` (PRD 2.4)."""
    row = {
        "id": new_uuid(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """Refresh ``updated_at`` and increment ``version`` for a mutated resource.

    A resource mutated more than once inside a single cascading request is
    bumped exactly once -- PRD section 3.3 says the institution's version "is
    bumped once for the closing itself" even though the closing writes several
    of its fields.
    """
    if row is None:
        return row
    seen = _touched()
    row["updated_at"] = db.now_iso()
    if seen is not None:
        if id(row) in seen:
            return row
        seen.add(id(row))
    row["version"] = row.get("version", 1) + 1
    return row


def sort_key(row):
    """Default list ordering: ``created_at`` ascending, insertion-stable."""
    return (row.get("created_at") or "", row.get("_seq") or 0)


def ordered(rows):
    return sorted(rows, key=sort_key)
