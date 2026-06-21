"""Serialize stored entities to their public JSON view (strip internals)."""

_INTERNAL = {"_seq"}


def view(obj):
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if k not in _INTERNAL}


def view_list(objs):
    return [view(o) for o in objs]
