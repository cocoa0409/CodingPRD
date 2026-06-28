"""In-memory data store.

All state lives in plain Python dicts keyed by id. The store starts EMPTY on
every boot — no seeding, no preloading (per skill contract + per-test-server
isolation wipes state on each start.sh re-invocation).
"""
import uuid
from datetime import timezone

import clock

# ---- Entity tables (id -> dict) ----
doctors = {}
materials = {}
mill_machines = {}
courier_routes = {}
cases = {}
restorations = {}
fabrication_units = {}
shade_records = {}
mill_jobs = {}
route_stops = {}
invoices = {}
credit_memos = {}
remake_requests = {}

# Monotonic sequence to give a stable creation order tiebreaker for sorting,
# independent of timestamp collisions on the logical clock.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    """Server-minted UUID with no prefix (scaffold: 'no prefix. Identity only')."""
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # milliseconds = 3 fractional digits
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(record, initial_version=1):
    """Set system audit fields on a freshly created record (PRD §2.4).

    created_at, updated_at set to current logical clock; version begins at its
    initial value (1).
    """
    ts = clock.now()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = initial_version
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Mark a record mutated: refresh updated_at and increment version (PRD §2.4)."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + 1
