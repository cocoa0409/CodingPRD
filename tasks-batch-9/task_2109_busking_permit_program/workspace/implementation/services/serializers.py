"""Entity serialization.

`created_at` and `updated_at` are system timestamps and always carry three
fractional digits (PRD section 2.4); domain instants echo the resolution they
were stored with.  Internal bookkeeping keys are never exposed.
"""
from datetime import datetime

from utils import fmt_dt, fmt_ts


def serialize(ent):
    out = {}
    for key, value in ent.items():
        if key.startswith("_"):
            continue
        if key in ("created_at", "updated_at"):
            out[key] = fmt_ts(value)
        elif isinstance(value, datetime):
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    return out


def serialize_many(rows):
    return [serialize(row) for row in rows]
