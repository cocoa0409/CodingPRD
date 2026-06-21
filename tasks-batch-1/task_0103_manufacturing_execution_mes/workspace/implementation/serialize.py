"""Serialize stored records to API output, stripping internal-only fields."""

# Fields that are internal bookkeeping and must never appear in API output.
_INTERNAL = {"_seq"}


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if k not in _INTERNAL}


def public_list(recs):
    return [public(r) for r in recs]
