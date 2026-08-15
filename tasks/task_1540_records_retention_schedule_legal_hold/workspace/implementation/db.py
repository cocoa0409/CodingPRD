"""In-memory data store and logical clock.

The store starts completely empty on every boot. No entity is ever seeded,
preloaded, or hardcoded; all state is built through the API surface.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.programs = {}
        self.record_classes = {}
        self.jurisdictions = {}
        self.custodians = {}
        self.retention_rules = {}
        self.retention_conflicts = {}
        self.records = {}
        self.legal_holds = {}
        self.hold_custodians = {}
        self.hold_scope_items = {}
        self.disposition_requests = {}
        self.disposition_items = {}
        self.destruction_certificates = {}
        self.hold_audits = {}
        self.reminder_logs = {}
        self.freeze_windows = {}
        # Per-program monotonically increasing certificate sequence.
        self.cert_seq = {}


db = Store()


# ---------------------------------------------------------------------------
# Logical clock. Startup default is exactly 2026-08-01T00:00:00Z; the clock
# never falls back to wall-clock time. Advanced only via POST
# /_clock/set_current_utc.
# ---------------------------------------------------------------------------
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _CLOCK_START


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    """Stamp common fields at creation."""
    entity["created_at"] = now()
    entity["updated_at"] = now()
    entity["version"] = 1


def bump(entity):
    """Stamp a mutation: version += 1 and updated_at refreshed."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now()
