"""In-memory data store.

State is per-process and starts empty on every boot. No seeding, no disk
persistence — the test harness restarts the server before every test and
constructs all required entities through the declared API surface.
"""
import threading
import uuid

from clock import Clock, to_iso8601_millis


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        # One dict per entity collection, keyed by id.
        self.jurisdictions = {}
        self.fee_schedules = {}
        self.notaries = {}
        self.bonds = {}
        self.renewals = {}
        self.sessions = {}
        self.signers = {}
        self.documents = {}
        self.journal_entries = {}
        self.complaints = {}
        self.audit_events = {}
        # Monotonic sequence so created_at ties have a deterministic order.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def now_iso(self):
        return to_iso8601_millis(self.clock.now())


# Module-level singleton. Reset only by process restart (per-test isolation).
store = Store()


def new_common_fields(with_version=True):
    """System-managed common fields for a primary resource.

    id, created_at, updated_at, version (PRD §2.4). AuditEvent opts out of
    version/updated_at (with_version=False).
    """
    now = store.now_iso()
    fields = {
        "id": store.new_id(),
        "created_at": now,
        "_seq": store.next_seq(),
    }
    if with_version:
        fields["updated_at"] = now
        fields["version"] = 1
    return fields


def touch(record):
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    record["updated_at"] = store.now_iso()
    record["version"] = record.get("version", 1) + 1
