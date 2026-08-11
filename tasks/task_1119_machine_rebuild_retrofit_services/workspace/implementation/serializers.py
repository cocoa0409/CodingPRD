"""Entity serialization: strip internal fields, convert Decimal to float."""

from decimal import Decimal


def serialize(rec):
    if rec is None:
        return None
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def serialize_list(recs):
    return [serialize(r) for r in recs]
