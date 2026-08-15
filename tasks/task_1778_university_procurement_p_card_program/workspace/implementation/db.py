"""In-memory data store, logical clock, and id/sequence minting.

Storage is process-local only (plain dicts keyed by id). The store starts
empty on every boot; per-test-server isolation wipes state by restarting
the process. No entity is ever seeded at startup.

Timestamp policy (PRD/worklog): domain-event stamps (submitted_at, issued_at,
paid_at, received_at, posted_at, declared_at, executed_at, awarded_at,
reconciled_at, decided_at) read the LOGICAL clock; created_at / updated_at
and the response-meta timestamp read the WALL clock (created_at is the final
award tie-break, "wall").
"""

import uuid
from datetime import datetime, timezone

COLLECTIONS = [
    "departments",
    "vendors",
    "grants",
    "contracts",
    "requisitions",
    "approval_records",
    "solicitations",
    "quotes",
    "purchase_orders",
    "receipts",
    "invoices",
    "pcards",
    "limit_elevations",
    "pcard_transactions",
    "surplus_assets",
]

STORE = {name: {} for name in COLLECTIONS}

_SEQ = {"n": 0}

# Human-readable number counters.
_NUMBERS = {"requisition": 0, "purchase_order": 0}

# Logical clock: startup default is exactly 2026-08-01T00:00:00Z.
_CLOCK = {"dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    """Logical clock (used by every deadline/window/aging rule)."""
    return _CLOCK["dt"]


def set_clock(dt):
    _CLOCK["dt"] = dt


def wall_now():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def next_number(kind):
    """Sequential human-readable numbers: RQ-000001 / PO-000001."""
    _NUMBERS[kind] += 1
    prefix = "RQ" if kind == "requisition" else "PO"
    return "%s-%06d" % (prefix, _NUMBERS[kind])


def fmt_ts(dt):
    """Render an ISO 8601 UTC timestamp with three fractional digits."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def logical_ts():
    return fmt_ts(now())


def new_entity(collection, fields, common=True):
    """Create and store an entity with common system fields.

    common=False for the append-only ApprovalRecord (id + created_at only;
    no updated_at/version per PRD 2.5).
    """
    ent = dict(fields)
    ent["id"] = new_id()
    ent["created_at"] = fmt_ts(wall_now())
    if common:
        ent["updated_at"] = ent["created_at"]
        ent["version"] = 1
    ent["_seq"] = next_seq()
    STORE[collection][ent["id"]] = ent
    return ent


def touch(ent):
    """Record a mutation of a stored field: bump version and updated_at."""
    if "version" in ent:
        ent["version"] = ent["version"] + 1
        ent["updated_at"] = fmt_ts(wall_now())


def get(collection, ent_id):
    if not isinstance(ent_id, str):
        return None
    return STORE[collection].get(ent_id)


def all_of(collection):
    return sorted(STORE[collection].values(), key=lambda e: (e["created_at"], e["_seq"]))


def public(ent):
    """Strip internal keys for serialization."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
