"""Shared serializers: strip internal underscore-prefixed fields before output."""


def public(rec):
    if rec is None:
        return {}
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(recs):
    return [public(r) for r in recs]
