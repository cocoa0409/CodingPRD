"""Serialize internal records to API output (strip internal fields)."""

# Internal-only keys never exposed in responses.
_INTERNAL = {"_seq", "_type", "_observed_dt"}


def serialize(rec):
    if rec is None:
        return None
    out = {}
    for k, v in rec.items():
        if k in _INTERNAL:
            continue
        out[k] = v
    return out
