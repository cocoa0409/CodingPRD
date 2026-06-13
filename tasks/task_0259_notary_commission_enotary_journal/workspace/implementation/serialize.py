"""Public serialization: strip internal-only fields from stored records."""

_INTERNAL = {"_seq"}


def view(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def view_list(records):
    return [view(r) for r in records]
