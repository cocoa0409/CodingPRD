"""Record serialization: strip internal (underscore-prefixed) bookkeeping fields."""


def public(rec):
    """Return a copy of a record with internal fields removed."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(recs):
    return [public(r) for r in recs]
