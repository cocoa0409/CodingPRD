"""In-memory data store. Every collection starts EMPTY on each process boot.

No seeding, preloading, or hardcoded entities — tests build all state via the
declared API surface. State is wiped whenever the process restarts (the test
harness re-launches start.sh before every test).
"""
import itertools
import uuid
from datetime import datetime, timezone

# One dict per entity collection, keyed by id.
accounts = {}
plans = {}
devices = {}
lines = {}
sim_assignments = {}
installment_plans = {}
addons = {}
port_requests = {}
upgrade_orders = {}
billing_cycles = {}
charges = {}
usage_records = {}

# Monotonic counter so created_at ordering is stable for sort even when two
# records share the same millisecond timestamp.
_seq = itertools.count(1)

# Logical clock (PRD §3.11). Defaults to real wall-clock UTC until set.
_clock = {"now": None}


def reset():
    """Wipe all state — used at module import to guarantee a clean boot."""
    for coll in (accounts, plans, devices, lines, sim_assignments,
                 installment_plans, addons, port_requests, upgrade_orders,
                 billing_cycles, charges, usage_records):
        coll.clear()
    _clock["now"] = None


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def set_clock(dt):
    _clock["now"] = dt


def now():
    """Current logical UTC instant (clock override or wall clock)."""
    if _clock["now"] is not None:
        return _clock["now"]
    return datetime.now(timezone.utc)
