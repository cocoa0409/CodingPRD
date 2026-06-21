"""In-memory data store (PRD §2.4).

Every collection is a dict keyed by UUID id. The store starts EMPTY on every boot
and is never seeded — tests build all state via the declared API surface.

Common fields (PRD §2.4): most resources carry a system-minted `id` (UUID, no type
prefix), `created_at`, `updated_at`, `version` (starts at 1, +1 per mutation). The
sole exception is FeeSchedule, which carries only `id` and `created_at`.
"""

import threading
import uuid

from clock import clock


class DB:
    def __init__(self):
        self.owners = {}
        self.properties = {}
        self.fee_schedules = {}
        self.cases = {}
        self.complaints = {}
        self.inspections = {}
        self.notices = {}
        self.reinspections = {}
        self.fines = {}
        self.hearings = {}
        self.abatement_orders = {}
        self.liens = {}
        # Monotonic sequence to break created_at timestamp ties deterministically
        # (oldest-first fine allocation, ascending list sort).
        self._seq = 0
        self.lock = threading.RLock()

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits, or None."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def common_fields(with_version=True):
    """Build the system common fields for a new full record."""
    now = clock.now()
    fields = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "_seq": db.next_seq(),
    }
    if with_version:
        fields["version"] = 1
    return fields


def touch(record):
    """Mutation: refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = clock.now()
    if "version" in record:
        record["version"] = record["version"] + 1
