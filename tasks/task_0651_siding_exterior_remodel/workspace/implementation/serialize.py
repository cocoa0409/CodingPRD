"""Entity serialization. Strips internal bookkeeping fields (e.g. _seq) from the
stored dict before it goes out on the wire. Every stored entity already carries
exactly the public field set, so serialization is a shallow copy minus internals.
"""

_INTERNAL = {"_seq"}


def serialize(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if k not in _INTERNAL}
