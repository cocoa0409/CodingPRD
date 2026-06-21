"""Public serialization of entity records.

Strips internal-only fields (those prefixed with '_') from the response.
Ensures field ordering is irrelevant — JSON consumers key by name.
"""


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(recs):
    return [public(r) for r in recs]
