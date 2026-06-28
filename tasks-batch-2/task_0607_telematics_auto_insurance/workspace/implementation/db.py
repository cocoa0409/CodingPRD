"""In-memory data store (PRD §2.4).

Every collection is a plain dict keyed by the resource UUID. The store starts
EMPTY on every boot — no seeding, no preload, no hardcoded entities. Tests
build all required state through the declared API surface.

A per-process monotonic counter assigns insertion order so list endpoints can
sort by creation order deterministically even when two resources share the same
logical-clock created_at (PRD §2.3: sorted by created_at ascending).
"""
import threading
import uuid

LOCK = threading.RLock()

# One dict per entity collection, keyed by id.
rate_plans = {}
drivers = {}
privacy_consents = {}
enrollments = {}
quotes = {}
policies = {}
trips = {}
trip_events = {}
risk_snapshots = {}
statements = {}
renewals = {}
claims = {}
discount_banks = {}
discount_grants = {}

_seq = 0


def new_id() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def next_seq() -> int:
    global _seq
    _seq += 1
    return _seq
