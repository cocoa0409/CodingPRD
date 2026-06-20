"""In-memory data store. All state lives in module-level dicts keyed by id.

State is wiped on every process start (start.sh re-invocation). Nothing is
seeded — every entity is created by a test through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone

# One dict per entity collection: id -> record (plain dict).
properties = {}
utilities = {}
units = {}
meters = {}
leases = {}
vendor_bills = {}
meter_reads = {}
billing_cycles = {}
tenant_statements = {}
disputes = {}
payments = {}

# Monotonic insertion counter to give every record a stable creation order
# (used for created_at ASC tie-breaks in allocations and list sorting).
_seq_counter = 0
_lock = threading.RLock()

# Logical server clock. Defaults to real now; overridable via /_clock.
_server_clock = datetime.now(timezone.utc)


def reset():
    """Clear all collections (not used at runtime, but keeps a clean entry point)."""
    global _seq_counter, _server_clock
    for coll in (
        properties, utilities, units, meters, leases, vendor_bills,
        meter_reads, billing_cycles, tenant_statements, disputes, payments,
    ):
        coll.clear()
    _seq_counter = 0
    _server_clock = datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC, three fractional digits, Z suffix (for created_at/updated_at)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def stamp_create(record):
    """Attach common system fields on creation (PRD §2.4)."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Mark a record mutated: bump version + updated_at (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


# ----- server clock --------------------------------------------------------

def set_clock(dt):
    global _server_clock
    _server_clock = dt


def get_clock():
    return _server_clock
