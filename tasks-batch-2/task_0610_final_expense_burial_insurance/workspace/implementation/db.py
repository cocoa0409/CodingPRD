"""In-memory data store.

Every collection is a plain dict keyed by the resource id. The store starts
EMPTY on every boot — nothing is seeded, preloaded, or hardcoded. Tests build
all preconditions through the declared API surface.
"""
import threading
import uuid

from clock import get_now, format_iso_millis

LOCK = threading.RLock()

# One dict per entity collection, keyed by id.
product_plans = {}
applicants = {}
applications = {}
health_questionnaires = {}
policies = {}
beneficiaries = {}
funeral_home_assignments = {}
premium_payments = {}
policy_loans = {}
claims = {}
death_certificates = {}
ledger_entries = {}

# Monotonic insertion counter, used to break ties on created_at (which is the
# logical clock and may repeat when the clock has not advanced). Sorting by
# created_at ASC then by this sequence yields deterministic, creation-time order.
_seq = {"n": 0}


def reset():
    for coll in (
        product_plans, applicants, applications, health_questionnaires,
        policies, beneficiaries, funeral_home_assignments, premium_payments,
        policy_loans, claims, death_certificates, ledger_entries,
    ):
        coll.clear()
    _seq["n"] = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def stamp_full(entity):
    """Attach the full system-managed quartet (id, created_at, updated_at, version)."""
    now = format_iso_millis(get_now())
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def stamp_light(entity):
    """Attach the lightweight pair (id, created_at) — no updated_at, no version."""
    now = format_iso_millis(get_now())
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = format_iso_millis(get_now())
    entity["version"] = entity.get("version", 1) + 1
