"""Serialize internal records to API output shape (strip internal helper keys)."""

_INTERNAL = {"_seq"}


def serialize(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def serialize_list(records):
    return [serialize(r) for r in records]
