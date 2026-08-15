"""Serialization: strip internal underscore-prefixed bookkeeping fields."""


def public(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def public_list(entities):
    return [public(e) for e in entities]
