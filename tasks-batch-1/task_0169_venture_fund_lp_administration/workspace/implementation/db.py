"""In-memory data store. Dicts keyed by id.

STATE STARTS EMPTY ON EVERY BOOT. No seeding, no preload. Tests build all
state via the API surface. Per-test-server isolation wipes this on each
start.sh re-invocation (a fresh process always starts here).

Common fields (PRD §2.4):
  - id: UUID with no type prefix
  - created_at: ISO 8601 UTC, three fractional digits, set once
  - updated_at: refreshed on every mutation
  - version: integer, starts at 1, increments by 1 on each mutation
"""
import threading
import uuid

from response import now_iso

# One dict per entity type, keyed by id.
funds = {}
limited_partners = {}
commitments = {}
capital_calls = {}
capital_call_allocations = {}
portfolio_companies = {}
investments = {}
valuation_marks = {}
management_fee_accruals = {}
distribution_events = {}
distribution_allocations = {}
side_letters = {}

# Per-fund monotonic call_number counter (call_number assigned on issuance).
_call_number_counters = {}

# Single global lock; consistency_model is immediate, all mutations atomic
# within a request.
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def stamp_new(obj):
    """Set the common system fields on creation."""
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at and bump version on mutation (PRD §2.4 / §2.6)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def next_call_number(fund_id):
    n = _call_number_counters.get(fund_id, 0) + 1
    _call_number_counters[fund_id] = n
    return n
