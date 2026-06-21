"""In-memory data store. Starts EMPTY on every boot — no seeding ever.

Each collection is a dict keyed by entity id. A monotonic sequence is used
only to preserve stable creation ordering for created_at tie-breaks when two
records are minted in the same millisecond.
"""
import uuid

from response import now_iso


class Store:
    def __init__(self):
        # Mutable, versioned entities
        self.students = {}
        self.guardians = {}
        self.vehicles = {}
        self.scholarship_pools = {}
        self.field_trips = {}
        self.permission_slips = {}
        self.scholarship_grants = {}
        self.chaperones = {}
        self.transport_bookings = {}
        # Append-only / immutable records (id + created_at only)
        self.trip_approvals = {}
        self.emergency_contacts = {}
        self.fee_transactions = {}
        self.attendance_records = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(versioned=True):
    """Return the system fields for a freshly created record.

    versioned=True -> mutable record with created_at/updated_at/version.
    versioned=False -> append-only record with only created_at.
    """
    ts = now_iso()
    base = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if versioned:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(record):
    """Bump updated_at + version on a versioned record (PRD §2.4 / §2.5)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
