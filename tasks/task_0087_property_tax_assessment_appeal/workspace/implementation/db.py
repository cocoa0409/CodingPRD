"""In-memory data store (PRD §2.4).

Every collection is a plain dict keyed by the resource's UUID id. The store
starts EMPTY on every process boot — nothing is seeded, preloaded, or
hardcoded. Tests construct every entity through the declared API surface.
`start.sh` re-invocation (per-test-server isolation) wipes all state because
the process restarts and these module-level dicts are re-initialised empty.
"""
import threading
import uuid

from response import now_iso

# A single lock guards all mutations so cascades resolve atomically per request.
LOCK = threading.RLock()

# One dict per entity, keyed by id.
tax_rolls = {}
owners = {}
parcels = {}
assessments = {}
exemptions = {}
appeals = {}
board_panels = {}
hearings = {}
deferral_agreements = {}
deferral_payments = {}
tax_bills = {}


def new_id():
    return str(uuid.uuid4())


def init_common(record):
    """Stamp id, created_at, updated_at, version (PRD §2.4)."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def init_event(record):
    """Append-only event resource: only id and created_at (DeferralPayment)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    return record


def touch(record):
    """Refresh updated_at and advance version on any mutation (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
