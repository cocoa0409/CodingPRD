"""Serializers: entity dict -> API representation (PRD 2.5 common fields).

Internal bookkeeping keys (prefixed with "_") and Decimal values are coerced
to JSON-safe types. 2dp decimals serialize as numbers (int when integral).
"""

from decimal import Decimal


def _coerce(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def serialize(resource):
    out = {}
    for key, value in resource.items():
        if key.startswith("_"):
            continue
        out[key] = _coerce(value)
    return out


def serialize_many(resources):
    return [serialize(r) for r in resources]
