"""Serialize entities to public JSON. We store entities as dicts already in
public shape, so serialization mostly strips internal-only keys."""

# Internal-only keys that must never be exposed
_INTERNAL = {"_activated_by"}


def public(obj):
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if k not in _INTERNAL}
