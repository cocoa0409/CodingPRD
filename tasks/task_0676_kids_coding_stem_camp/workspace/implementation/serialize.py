"""Convert internal entity dicts into API output dicts (strip internal keys)."""

_INTERNAL = {"_seq"}


def out(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if k not in _INTERNAL}
