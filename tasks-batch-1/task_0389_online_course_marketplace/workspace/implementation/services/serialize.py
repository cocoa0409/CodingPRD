"""Public serialization: strip internal keys (those starting with '_')."""


def view(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def view_list(recs):
    return [view(r) for r in recs]
