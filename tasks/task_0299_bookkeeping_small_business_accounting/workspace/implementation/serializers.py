"""Serialize internal records to public JSON shape.

Strips internal-only fields (those prefixed with '_'). Computed fields are
stored on the record (kept fresh by the ledger engine / recompute helpers) so a
plain copy is sufficient.
"""


def serialize(rec):
    if rec is None:
        return {}
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def serialize_list(recs):
    return [serialize(r) for r in recs]
