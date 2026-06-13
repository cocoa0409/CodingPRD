"""In-memory data store.

The store starts EMPTY on every boot. No seeding, preloading, or hardcoded
entities — every entity a test needs is built through the declared API surface.
(prd-bench: per-test-server isolation re-launches start.sh before each test.)
"""
import threading
import uuid
from datetime import datetime, timezone

_lock = threading.RLock()

# First-class + ledger entity collections, keyed by id.
service_plans = {}
customers = {}
sites = {}
memberships = {}
equipment = {}
technicians = {}
service_visits = {}
refrigerant_logs = {}
part_usages = {}
warranty_claims = {}
renewal_offers = {}

# Monotonic sequence to provide a stable created_at tie-break / insertion order.
_seq = 0

# Logical UTC clock (PRD §3.11). Defaults to real wall-clock UTC until set.
_clock = None


def lock():
    return _lock


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Server/meta timestamp: ISO 8601 UTC with three fractional digits (PRD §2.2)."""
    return iso(datetime.now(timezone.utc))


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits + Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def get_clock():
    """Current logical UTC clock instant (datetime, tz-aware)."""
    global _clock
    if _clock is None:
        return datetime.now(timezone.utc)
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def reset():
    """Test-only convenience; not invoked at startup."""
    global _seq, _clock
    for coll in (
        service_plans, customers, sites, memberships, equipment, technicians,
        service_visits, refrigerant_logs, part_usages, warranty_claims,
        renewal_offers,
    ):
        coll.clear()
    _seq = 0
    _clock = None
