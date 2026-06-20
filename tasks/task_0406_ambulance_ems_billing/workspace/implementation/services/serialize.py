"""Serialization: strip internal fields and present the public entity shape.

Each entity record stores all of its public fields plus a private "_seq"
ordering key. Serialization drops keys whose name begins with an underscore.
"""


def serialize(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_list(records):
    return [serialize(r) for r in records]
