"""In-memory data store.

State lives only in module-level dicts keyed by id. Every start.sh invocation
boots a fresh process, so all state is wiped on every restart. NO entity data is
ever seeded, preloaded, or hardcoded here — every entity is built by tests via
the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone

# A global lock to keep multi-step mutations atomic under Flask's threaded server.
LOCK = threading.RLock()

# One dict per entity type, keyed by id. These start empty and stay empty until a
# test creates entities through the API.
clients = {}
retainer_packages = {}
channels = {}
content_items = {}
content_targets = {}
schedule_slots = {}
boost_campaigns = {}
conversations = {}
messages = {}
influencer_collabs = {}
ugc_assets = {}
analytics_snapshots = {}
ledger_entries = {}

# Monotonic insertion counter so we can sort by creation order deterministically
# even when two rows share an identical created_at timestamp.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(obj, full=True):
    """Set system-managed creation fields.

    full resources carry created_at, updated_at, version; lightweight records
    carry only created_at (PRD §2.4).
    """
    obj["created_at"] = now_iso()
    if full:
        obj["updated_at"] = obj["created_at"]
        obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def touch(obj):
    """Refresh updated_at and bump version on every mutation of a full resource."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
