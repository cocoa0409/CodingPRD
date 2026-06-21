"""Serializers — produce the public JSON view of each entity.

Entities are stored as plain dicts with exactly their public fields plus internal
bookkeeping keys prefixed with '_'. Serialization drops the '_'-prefixed keys.
"""


def public(entity):
    """Return a copy of the entity with internal (_-prefixed) keys removed."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
