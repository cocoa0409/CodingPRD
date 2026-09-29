"""In-memory data store and the logical clock (PRD 2.5).

The store starts completely empty on every boot: nothing is seeded.
"""
import itertools
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "programs",
    "competitors",
    "deals",
    "analysts",
    "buyer_contacts",
    "sampling_frames",
    "interviews",
    "interview_responses",
    "loss_reasons",
    "loss_attributions",
    "battlecards",
    "battlecard_claims",
    "product_gaps",
    "enablement_assignments",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(extra=None):
    """Build a row carrying the four common system-managed properties."""
    row = {
        "id": new_id(),
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """Mutation bookkeeping: refresh updated_at and bump version (PRD 2.4)."""
    row["updated_at"] = db.clock
    row["version"] = row.get("version", 1) + 1
    return row


class DerivedWatch(object):
    """Bump version/updated_at only for rows whose derived fields actually moved.

    PRD 2.11: every row whose derived fields changed has its updated_at
    refreshed and its version incremented.
    """

    def __init__(self):
        self._watched = []

    def watch(self, row, compute):
        if row is None:
            return
        for existing, _, _ in self._watched:
            if existing is row:
                return
        self._watched.append((row, compute, compute(row)))

    def commit(self):
        changed = []
        for row, compute, before in self._watched:
            if compute(row) != before:
                touch(row)
                changed.append(row)
        self._watched = []
        return changed
