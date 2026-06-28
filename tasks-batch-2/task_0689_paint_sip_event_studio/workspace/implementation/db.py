"""In-memory data store.

Storage is in-memory only (plain dicts). Every boot starts completely empty so
that per-test-server isolation wipes all state. No seeding, no preloading.
"""
import itertools
import uuid
from datetime import datetime, timezone

# One dict per entity type, keyed by id.
studios = {}
artists = {}
customers = {}
events = {}
assignments = {}
kit_batches = {}
reservations = {}
attendees = {}
walk_ins = {}
gift_cards = {}
payments = {}

# Monotonic sequence to provide a stable, strictly-increasing creation order
# independent of timestamp resolution (the logical clock has 1s granularity at
# best for some operations, and created_at uses wall clock anyway).
_seq = itertools.count(1)


def reset():
    """Clear every store. Used only if explicitly invoked (not at boot)."""
    for d in (studios, artists, customers, events, assignments, kit_batches,
              reservations, attendees, walk_ins, gift_cards, payments):
        d.clear()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def now_iso():
    """Wall-clock ISO 8601 UTC with three fractional digits, e.g. ...Z.

    Used for created_at / updated_at / api_request_timestamp. The logical clock
    is separate and governs business-time rules only.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
