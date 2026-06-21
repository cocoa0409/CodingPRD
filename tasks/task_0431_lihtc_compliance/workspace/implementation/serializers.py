"""Project entities to their public JSON representation.

Strips internal bookkeeping fields (those prefixed with '_').
"""


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]


def sort_by_created(records):
    """List endpoints sort by created_at ascending (creation order, §2.3).

    Tie-break on the internal monotonic sequence so identical timestamps keep
    a stable creation order.
    """
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
