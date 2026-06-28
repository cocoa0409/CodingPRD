"""In-memory data store. Starts EMPTY on every boot — no seeding, ever.

All entities keyed by id in plain dicts. The logical clock (PRD §2.9) starts at
2026-01-01T00:00:00Z and only moves on explicit set.
"""
import itertools
import uuid
from datetime import datetime, timezone

from response import now_iso

# ---- Entity stores (all empty at boot) ----
funds = {}
share_classes = {}
projects = {}
investors = {}
subscriptions = {}
holdings = {}
valuations = {}
distributions = {}
allocations = {}
redemption_requests = {}
tax_documents = {}

# ---- Monotonic counters ----
_redemption_queue_seq = itertools.count(1)
_insertion_seq = itertools.count(1)

# ---- Logical clock (PRD §2.9): default 2026-01-01T00:00:00Z ----
_clock = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def reset():
    """Wipe all state. Called once at module import; store boots empty."""
    global _redemption_queue_seq, _insertion_seq, _clock
    funds.clear()
    share_classes.clear()
    projects.clear()
    investors.clear()
    subscriptions.clear()
    holdings.clear()
    valuations.clear()
    distributions.clear()
    allocations.clear()
    redemption_requests.clear()
    tax_documents.clear()
    _redemption_queue_seq = itertools.count(1)
    _insertion_seq = itertools.count(1)
    _clock = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_id():
    return str(uuid.uuid4())


def next_queue_seq():
    return next(_redemption_queue_seq)


def next_insertion_seq():
    """Internal ordering key for created_at-ascending stable sort."""
    return next(_insertion_seq)


def clock_now():
    return _clock


def clock_year():
    return _clock.year


def set_clock(dt):
    global _clock
    _clock = dt


def base_fields(full=True):
    """Common server-minted fields. full=True adds updated_at + version (PRD §2.4)."""
    ts = now_iso()
    fields = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_insertion_seq(),
    }
    if full:
        fields["updated_at"] = ts
        fields["version"] = 1
    return fields


def touch(entity):
    """Mutation: bump version + refresh updated_at (PRD §2.4)."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()
