"""Row -> JSON projection.  Datetimes become ISO-8601 UTC with 3 fractional digits."""
from datetime import datetime

import clock

_INTERNAL = ("_seq",)


def _val(v):
    if isinstance(v, datetime):
        return clock.fmt(v)
    if isinstance(v, list):
        return [_val(x) for x in v]
    if isinstance(v, dict):
        return {k: _val(x) for k, x in v.items()}
    return v


def view(row):
    if row is None:
        return None
    out = {}
    for k, v in row.items():
        if k in _INTERNAL or k.startswith("_"):
            continue
        out[k] = _val(v)
    return out


def views(rows):
    return [view(r) for r in rows]
