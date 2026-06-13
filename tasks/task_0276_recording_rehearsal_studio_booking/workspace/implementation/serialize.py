"""Record -> response-body serialization. Strips internal bookkeeping keys."""

# Keys that are internal and must never appear in API output.
_INTERNAL = {"_seq", "_contract_id"}


def public(record):
    """Return a shallow copy of the record without internal keys."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def public_list(records):
    return [public(r) for r in records]
