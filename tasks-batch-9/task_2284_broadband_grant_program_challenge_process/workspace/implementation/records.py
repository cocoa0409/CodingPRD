"""Mutation helpers.

PRD section 2.4: every mutation refreshes ``updated_at`` and increments
``version`` by one.  A single API request that changes several attributes of the
same row (a state transition plus the derived fields recomputed alongside it) is
one mutation, so ``touch`` is idempotent within a request.
"""

from flask import g

from db import now_ts


def _touched():
    bag = getattr(g, "_touched_rows", None)
    if bag is None:
        bag = set()
        setattr(g, "_touched_rows", bag)
    return bag


def touch(rec):
    """Bump updated_at/version at most once per row per request."""
    if rec is None or "version" not in rec:
        return
    bag = _touched()
    key = rec.get("id")
    if key in bag:
        rec["updated_at"] = now_ts()
        return
    bag.add(key)
    rec["updated_at"] = now_ts()
    rec["version"] = int(rec.get("version") or 0) + 1


def assign(rec, field, value):
    """Set a field, returning True when the stored value actually changed."""
    if rec.get(field) == value and (field in rec):
        return False
    rec[field] = value
    return True
