"""Entity -> JSON serialization.

Stored entity dicts already contain exactly the public fields (plus internal
keys prefixed with '_'); serialization just strips the internal keys and
normalizes Decimal ratios to floats.
"""
from decimal import Decimal


def serialize(entity):
    if entity is None:
        return None
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def serialize_list(entities):
    return [serialize(e) for e in entities]
