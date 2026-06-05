def public(obj):
    """Return a copy with internal (underscore-prefixed) keys removed."""
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def public_list(objs):
    return [public(o) for o in objs]
