"""In-memory data store + logical clock.

State starts EMPTY on every boot. No seeding/preloading of any entity data.
"""
import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.families = {}
        self.students = {}
        self.terms = {}
        self.rooms = {}
        self.instructors = {}
        self.sections = {}
        self.sessions = {}
        self.enrollments = {}
        self.attendance = {}
        self.costumes = {}
        self.costume_orders = {}
        self.recitals = {}
        self.seats = {}
        self.teams = {}
        self.memberships = {}
        self.trips = {}
        self.participants = {}
        self.invoices = {}

        # Logical clock: server startup default per PRD 2.4.
        self.clock = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Monotonic counter to provide a stable secondary ordering for created_at
        # ties (records minted in the same millisecond keep insertion order).
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with three fractional digits, derived from the logical clock."""
    c = db.clock
    return c.strftime("%Y-%m-%dT%H:%M:%S.") + f"{c.microsecond // 1000:03d}Z"


def common_fields():
    """created_at / updated_at / version for a fresh resource (PRD 2.4)."""
    ts = now_iso()
    return {
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(resource):
    """Refresh updated_at and bump version on a mutation (PRD 2.4 / 2.6)."""
    if "version" in resource:
        resource["version"] += 1
    if "updated_at" in resource:
        resource["updated_at"] = now_iso()
