"""Convert internal records to their public JSON representation."""
from decimal import Decimal

import store


def _base(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def public(rec):
    out = _base(rec)
    if rec.get("_kind") == "certificate":
        # status is derived on read from the logical clock
        exp = rec.get("_expires_dt")
        if exp is not None:
            out["status"] = "VALID" if store.clock_now() <= exp else "EXPIRED"
    return out


def public_list(recs):
    return [public(r) for r in recs]
