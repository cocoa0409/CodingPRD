"""In-memory stores, logical clock, and common-field stamping (PRD 2.4).

Storage is in-memory only: plain dicts keyed by id. The store starts EMPTY on
every boot; nothing is seeded or preloaded. The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""
import uuid

from util import now_iso, parse_dt

STORES = {
    "sponsors": {},
    "persons": {},
    "awards": {},
    "budget_lines": {},
    "commitments": {},
    "expenditures": {},
    "transfers": {},
    "cycles": {},
    "statements": {},
    "subawards": {},
    "invoices": {},
    "reports": {},
    "drawdowns": {},
    "receivables": {},
    "modifications": {},
    "ffrs": {},
}

# Logical clock (PRD 2.4): startup default exactly 2026-08-01T00:00:00Z.
CLOCK = {"current": parse_dt("2026-08-01T00:00:00Z")}


def now_clock():
    return CLOCK["current"]


def set_clock(dt):
    CLOCK["current"] = dt


def new_id():
    """UUID with no type prefix."""
    return str(uuid.uuid4())


def stamp_new(entity):
    """Common fields on creation: created_at/updated_at/version (version starts at 1)."""
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    """Every mutation bumps updated_at and version by one (PRD 2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1
    return entity


def get(store, rid):
    return STORES[store].get(rid)
