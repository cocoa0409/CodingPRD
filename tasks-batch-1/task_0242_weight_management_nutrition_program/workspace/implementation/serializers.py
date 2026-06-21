"""Serialise internal entity dicts to public response shapes.

We store entities as plain dicts already shaped like the API output, plus a
private `_seq` (and, for some, internal-only helper keys). Serialisation just
strips private keys (those prefixed with `_`).
"""


def _strip(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def serialize(obj):
    return _strip(obj)


def serialize_list(objs):
    return [_strip(o) for o in objs]
