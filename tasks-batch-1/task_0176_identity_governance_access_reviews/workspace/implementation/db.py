"""In-memory data store.

All state lives in module-level dicts keyed by id. Every process boot starts
EMPTY — there is no seeding, preloading, or hardcoded data anywhere. The
per-test-server harness relaunches start.sh before every test, which wipes all
state by virtue of being a fresh process.
"""
import threading
import uuid
from datetime import datetime, timezone

from response import now_iso

# A single coarse lock makes each request handler atomic, which is what the
# concurrency / OCC semantics in the PRD assume (immediate consistency).
LOCK = threading.RLock()

# One dict per entity type, keyed by id.
entitlements = {}
roles = {}
sod_policies = {}
identities = {}
access_requests = {}
grants = {}
certification_campaigns = {}
certification_items = {}
audit_events = {}

# Monotonic sequence to break created_at ties deterministically (creation order).
_seq = 0

# Server clock override (set via POST /_clock/set_current_utc). None -> real UTC.
_clock_override = None


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def new_common(with_version=True):
    """Common system fields applied at creation time."""
    ts = now_iso()
    fields = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "_seq": next_seq(),
    }
    if with_version:
        fields["version"] = 1
    return fields


def touch(record):
    """Bump version + updated_at for a mutation (including cascaded ones)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()


# --- Server clock -----------------------------------------------------------
def set_clock(dt):
    global _clock_override
    _clock_override = dt


def current_utc():
    """Return the current server clock as an aware UTC datetime."""
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)
