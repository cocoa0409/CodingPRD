"""In-memory data store. Empty on every boot -- the implementation never seeds,
preloads, or hardcodes any entity. Every record is created via the declared API."""

import itertools

_store = {
    "clubs": {},
    "volunteers": {},
    "members": {},
    "projects": {},
    "animal_tags": {},
    "record_books": {},
    "ledger_entries": {},
    "meetings": {},
    "rooms": {},
    "attendance": {},
    "fair_entries": {},
    "stall_assignments": {},
    "pens": {},
    "award_applications": {},
    "scholarship_apps": {},
    "screening_events": {},
    "treasury_transactions": {},
}

_seq = itertools.count(1)


def next_seq():
    """Monotonic insertion counter used as a stable sort tiebreak (records can
    share a created_at because the program-year logical clock is frozen until
    explicitly advanced)."""
    return next(_seq)


def table(name):
    return _store[name]
