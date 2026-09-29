"""In-memory data store for the Restaurant Brand Standards Audit API.

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded.  Every record any client needs is created through the declared
HTTP surface.
"""

import threading
import uuid
from datetime import datetime, timezone

# PRD 2.4: before any client sets it, the logical clock reads exactly this
# instant, and it never falls back to wall-clock time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "brands",
    "franchisees",
    "auditors",
    "locations",
    "rubric_versions",
    "rubric_items",
    "audit_visits",
    "scored_items",
    "corrective_actions",
    "evidence_photos",
    "disputes",
    "health_inspections",
    "calibration_records",
    "escalation_events",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = INITIAL_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()

# All request handling is serialized: the domain logic performs multi-record
# cascades that must not interleave.
request_lock = threading.RLock()


def now():
    """Current logical clock instant."""
    return store.clock


def new_id():
    return str(uuid.uuid4())


def new_record(light=False):
    """Create a record carrying the server-managed common fields.

    ``light`` records (RubricItem, EvidencePhoto, CalibrationRecord,
    EscalationEvent) carry only ``id`` and ``created_at``.
    """
    rec = {
        "id": new_id(),
        "created_at": store.clock,
        "_seq": store.next_seq(),
    }
    if not light:
        rec["updated_at"] = store.clock
        rec["version"] = 1
    return rec


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])
