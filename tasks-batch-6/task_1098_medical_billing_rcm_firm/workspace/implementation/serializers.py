"""Generic serialization: drop private keys, render datetimes uniformly."""
from datetime import datetime

import store


def serialize(record):
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = store.render_dt(v)
        else:
            out[k] = v
    return out
