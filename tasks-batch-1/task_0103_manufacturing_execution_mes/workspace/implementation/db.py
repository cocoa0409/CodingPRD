"""In-memory data store.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every process boot — nothing is seeded, preloaded, or hardcoded. Each
`start.sh` re-invocation re-imports this module fresh, wiping all state.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# A global lock to keep multi-step mutations atomic under the Flask threaded
# server.
LOCK = threading.RLock()

# One dict per entity collection, keyed by id.
products = {}
bom_lines = {}
routings = {}
operations = {}
machines = {}
machine_run_logs = {}
work_orders = {}
component_demands = {}
work_order_operations = {}
lots = {}
lot_issues = {}
genealogy_links = {}
scrap_dispositions = {}
traveler_signoffs = {}

# Monotonic creation sequence so list ordering by created_at is stable even when
# two records share the same millisecond timestamp.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    return next(_seq)


def new_record(with_version=True):
    """Build a fresh record with the system-managed common fields.

    PRD §2.4: id (UUID, no prefix), created_at, updated_at, version (starts at 1,
    +1 on every mutation). TravelerSignoff opts out (with_version=False) — it
    carries only id and created_at.
    """
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a record as mutated: refresh updated_at and bump version by one."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
