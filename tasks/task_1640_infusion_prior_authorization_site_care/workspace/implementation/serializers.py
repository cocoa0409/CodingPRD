"""Record -> wire serialization: datetimes to ISO strings, internal keys stripped."""
from datetime import datetime

from util import fmt_dt


def serialize(rec):
    if rec is None:
        return None
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = fmt_dt(value) if isinstance(value, datetime) else value
    return out
