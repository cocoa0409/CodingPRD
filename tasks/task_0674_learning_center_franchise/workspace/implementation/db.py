"""In-memory data store.

The store starts EMPTY on every boot. Tests build all preconditions via the
declared API surface. No seeding here.

Common fields (PRD §2.4): every resource carries id (UUID, no prefix),
created_at, updated_at (ISO 8601 UTC, 3 fractional digits), and an integer
version starting at 1 and incrementing by exactly 1 on every mutation.
"""
import uuid

from clock import clock


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.centers = {}
        self.agreements = {}
        self.subjects = {}
        self.levels = {}
        self.families = {}
        self.students = {}
        self.enrollments = {}
        self.worksheets = {}
        self.sessions = {}
        self.attendance = {}
        self.invoices = {}
        # monotonic sequence to break created_at ties deterministically in
        # insertion order (created_at may collide because the logical clock
        # is static unless advanced).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def stamp_create(self, obj):
        now = fmt_ts(clock.now())
        obj["id"] = self.new_id()
        obj["created_at"] = now
        obj["updated_at"] = now
        obj["version"] = 1
        obj["_seq"] = self.next_seq()

    def touch(self, obj):
        """Refresh updated_at and increment version (any mutation)."""
        obj["updated_at"] = fmt_ts(clock.now())
        obj["version"] = obj.get("version", 1) + 1


db = Store()


# Public (response-visible) field projection per entity. Internal bookkeeping
# fields (those starting with "_") are stripped on serialization.
def public(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}
