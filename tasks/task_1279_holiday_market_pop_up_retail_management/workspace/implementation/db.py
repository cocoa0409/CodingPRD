"""In-memory data store.

Storage is process-local Python dicts keyed by id. The store starts empty on
every boot; nothing is seeded. There is no external persistence of any kind.
"""
import itertools
import uuid

STORES = {
    "markets": {},
    "vendors": {},
    "applications": {},
    "booths": {},
    "assignments": {},
    "permits": {},
    "hookups": {},
    "pos_devices": {},
    "settlements": {},
    "programming": {},
    "load_slots": {},
    "weather_events": {},
    "renewal_offers": {},
}

_seq = itertools.count(1)


def new_id():
    """Server-minted UUID with no type prefix (canonical 8-4-4-4-12 form)."""
    return str(uuid.uuid4())


def next_seq():
    """Monotone insertion sequence used as a stable secondary sort key."""
    return next(_seq)
