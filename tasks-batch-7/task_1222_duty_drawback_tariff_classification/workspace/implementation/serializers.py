"""Entity serialization: strip internal keys, render datetimes canonically."""
from datetime import datetime

from util import fmt_dt


def serialize(entity):
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    return out


def sorted_by_creation(entities):
    return sorted(entities, key=lambda e: e["_seq"])
