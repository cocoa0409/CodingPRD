"""In-memory data store.

All state lives in module-level dicts keyed by id. There is NO persistence:
every process boot starts with empty collections, which is exactly what the
per-test-server isolation harness requires (start.sh re-launch wipes state).

Nothing is seeded here. Every entity is created by tests via the API surface.
"""

import datetime
import threading
import uuid

# Each collection is a dict id -> entity record (plain dict).
ACCOUNTS = {}
SITES = {}
CONTRACTS = {}
PLANS = {}
CREWS = {}
ROUTES = {}
VISITS = {}
ADDONS = {}
EQUIPMENT = {}
RESERVATIONS = {}
STORM_EVENTS = {}
INSPECTIONS = {}
INVOICES = {}

# Global monotonically-increasing sequence to provide a stable tie-break /
# insertion order when created_at timestamps collide (sub-millisecond creates).
_SEQ = 0
_LOCK = threading.RLock()


def reset():
    """Clear every collection. Used only for completeness; boot is already empty."""
    for coll in (ACCOUNTS, SITES, CONTRACTS, PLANS, CREWS, ROUTES, VISITS,
                 ADDONS, EQUIPMENT, RESERVATIONS, STORM_EVENTS, INSPECTIONS,
                 INVOICES):
        coll.clear()
    global _SEQ
    _SEQ = 0


def new_id():
    """Bare UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD 2.4)."""
    dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    global _SEQ
    with _LOCK:
        _SEQ += 1
        return _SEQ


def make_common(record):
    """Stamp the four common fields (id, created_at, updated_at, version)
    plus an internal _seq for stable ordering."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Mark a record mutated: refresh updated_at, bump version (PRD 2.4)."""
    record["updated_at"] = now_iso()
    record["version"] += 1


def public(record):
    """Strip internal-only keys (those beginning with '_') for API output."""
    return {k: v for k, v in record.items() if not k.startswith("_")}
