"""Public serialization of stored resources (strips internal fields)."""


def public(resource):
    """Return a copy with internal-only keys removed (any leading-underscore key)."""
    if resource is None:
        return None
    return {k: v for k, v in resource.items() if not k.startswith("_")}


def public_list(resources):
    return [public(r) for r in resources]
