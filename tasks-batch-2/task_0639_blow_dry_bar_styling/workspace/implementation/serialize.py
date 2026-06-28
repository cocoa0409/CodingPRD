"""Entity serialization: strip internal (underscore-prefixed) fields before
returning an entity in an API response."""


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def public_list(entities):
    return [public(e) for e in entities]
