"""In-memory data store and logical clock.

Storage is in-memory only: plain dicts keyed by id. No disk persistence.
The store starts empty on every boot; nothing is seeded.
"""
import uuid
from datetime import datetime, timezone

DB = {
    "dmrs": {},
    "lines": {},
    "suppliers": {},
    "agreements": {},
    "parts": {},
    "scns": {},
    "audits": {},
    "protocols": {},
    "studies": {},
    "lots": {},
    "components": {},
    "labels": {},
    "ncrs": {},
    "complaints": {},
    "capas": {},
    "field_actions": {},
}


class _Clock:
    """Deterministic logical clock. Starts exactly at 2026-08-01T00:00:00Z
    and never falls back to wall-clock afterwards."""

    def __init__(self):
        self.current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


CLOCK = _Clock()

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def now():
    return CLOCK.current


def new_id():
    return str(uuid.uuid4())


def new_entity(fields):
    """Create an entity dict with the four common system-managed properties."""
    t = now()
    e = {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def bump(obj):
    """Every mutation (including cascade-driven ones) refreshes updated_at
    and increments version."""
    obj["version"] += 1
    obj["updated_at"] = now()
