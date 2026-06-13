"""Public serialization of entities.

Strips internal bookkeeping (`_seq`) and presents derived/computed fields. For
entities whose derived fields are maintained on the record (account balances,
route booked_minutes, visit duration, etc.) we trust the stored value, which is
recomputed eagerly by the service layer after every contributing mutation.
"""

# Fields that are internal-only and must never appear in API output.
_HIDDEN = {"_seq"}


def public(rec):
    """Return a shallow copy of a record with internal fields removed."""
    return {k: v for k, v in rec.items() if k not in _HIDDEN}


def public_list(recs):
    return [public(r) for r in recs]
