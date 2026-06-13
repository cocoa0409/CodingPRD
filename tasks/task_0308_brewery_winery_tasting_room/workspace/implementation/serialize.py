"""Public serialization: strip internal keys (those starting with '_') from
the stored entity dict before returning it in the response envelope."""


def public(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def public_list(entities):
    return [public(e) for e in entities]
