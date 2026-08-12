"""In-memory data store and logical clock.

Storage is Python dicts keyed by id ONLY -- no SQLite, no JSON dump, no /tmp
cache, no external persistence. The store starts EMPTY on every boot; nothing
is seeded or preloaded anywhere in this module or at app startup.
"""
import itertools
import uuid
from datetime import datetime, timezone


class LogicalClock:
    """Logical clock. Startup default is exactly 2026-05-01T00:00:00Z and it
    advances only when a HealthAdmin sets it. It NEVER falls back to
    wall-clock time."""

    def __init__(self):
        self._now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()

# Entity tables: name -> {id: entity-dict}. Empty at startup.
db = {
    "students": {},
    "policies": {},
    "requirements": {},
    "records": {},
    "providers": {},
    "shifts": {},
    "appointments": {},
    "encounters": {},
    "prescriptions": {},
    "stocks": {},
    "lab_orders": {},
    "cases": {},
    "investigations": {},
    "invoices": {},
    "payments": {},
    "referrals": {},
    "pools": {},
}

_seq = itertools.count(1)


def new_entity():
    """Base system fields: id (UUID, identity only), created_at/updated_at
    (logical clock), version (1-based)."""
    now = clock.now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next(_seq),
    }


def bump(entity):
    """Every mutation (including cascaded side effects) increments version by
    1 and refreshes updated_at."""
    entity["version"] += 1
    entity["updated_at"] = clock.now()


def by_seq(entity):
    return (entity["created_at"], entity["_seq"])
