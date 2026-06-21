"""In-memory data store (PRD §2.4).

All state lives in module-level dicts keyed by UUID id. Nothing is persisted to
disk and nothing is seeded at import time — every entity is created by API calls.
A fresh process (start.sh re-invocation) therefore starts completely empty.
"""
import uuid
from datetime import datetime, timezone

# One dict per entity type, keyed by id.
carriers = {}
contract_rates = {}
orders = {}
shipments = {}
tenders = {}
loads = {}
dock_appointments = {}
freight_invoices = {}
claims = {}

# Monotonic sequence used purely to order records deterministically by creation
# even when two records share the same millisecond timestamp. NOT exposed to
# clients; created_at remains the sort key per PRD §2.3.
_seq = 0

# Logical UTC clock. At startup reads exactly 2026-01-01T00:00:00Z and never
# falls back to wall-clock time (PRD §2.4).
clock_iso = "2026-01-01T00:00:00Z"


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    # id is a UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def _now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def stamp_create(record):
    """Populate the common system fields on creation (PRD §2.4):
    id, created_at, updated_at, version (starts at 1), plus a private _seq."""
    ts = _now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version by one on every mutation (PRD §2.4/§2.5)."""
    record["updated_at"] = _now_iso()
    record["version"] = record["version"] + 1
