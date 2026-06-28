"""In-memory data store.

Starts EMPTY on every boot — nothing is seeded, preloaded, or hardcoded. Every
entity is created through the declared API surface. One dict per entity type,
keyed by id.

A process-global monotonically increasing sequence (`_seq`) is stamped onto each
row at creation as `_seq`. Because the logical clock can be set to identical
instants for many rows, created_at alone is not a stable tie-break; `_seq`
provides the deterministic "created_at ASC" ordering the PRD relies on for
pagination, waitlist promotion, and credit selection.
"""
import itertools

from clock import clock
from util import new_id, iso_ms


class DB:
    def __init__(self):
        self.families = {}
        self.children = {}
        self.memberships = {}
        self.programs = {}
        self.rooms = {}
        self.instructors = {}
        self.sessions = {}
        self.enrollments = {}
        self.attendance = {}
        self.credits = {}
        self.bookings = {}
        self.invoices = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()


def stamp_create(row, versioned=True):
    """Populate system fields at creation time.

    versioned=True entities carry id/created_at/updated_at/version. The two lean
    entities (AttendanceRecord, MakeupCredit) carry only id/created_at.
    """
    now_iso = iso_ms(clock.now())
    row.setdefault("id", new_id())
    row["created_at"] = now_iso
    row["_seq"] = db.next_seq()
    if versioned:
        row["updated_at"] = now_iso
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version by one (PRD 2.6) for versioned rows."""
    row["updated_at"] = iso_ms(clock.now())
    row["version"] = row.get("version", 1) + 1
    return row
