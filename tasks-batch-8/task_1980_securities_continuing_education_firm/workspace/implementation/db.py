"""In-memory data store and the server logical clock.

The store starts empty on every boot — no seeding anywhere. All entities any
caller needs are created through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.representatives = {}
        self.contents = {}
        self.sessions = {}
        self.enrollments = {}
        self.assignments = {}
        self.plans = {}
        self.attestations = {}
        self.products = {}
        self.certifications = {}
        self.licenses = {}
        self.blackouts = {}
        self.audit_events = {}
        # Global insertion sequence for deterministic ordering of same-second
        # created_at records.
        self.seq = itertools.count(1)


store = Store()

# ---------------------------------------------------------------------------
# Logical clock: defaults to exactly 2026-08-01T00:00:00Z; never wall clock.
# ---------------------------------------------------------------------------
_clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _clock["now"]


def clock_set(dt):
    _clock["now"] = dt


def new_id():
    return str(uuid.uuid4())


def base_record():
    """Standard system-managed fields for a primary resource."""
    now = clock_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next(store.seq),
    }


def touch(rec):
    """Every mutation (including cascade-driven) bumps version + updated_at."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = clock_now()


def audit(event_type, entity_type, entity_id, actor_user_id, actor_role, detail):
    """Append an entry to the audit evidence log (id + created_at only)."""
    rec = {
        "id": new_id(),
        "created_at": clock_now(),
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "detail": detail,
        "_seq": next(store.seq),
    }
    store.audit_events[rec["id"]] = rec
    return rec
