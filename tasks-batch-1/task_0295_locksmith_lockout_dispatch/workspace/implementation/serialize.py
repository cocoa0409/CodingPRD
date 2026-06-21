"""Serialize internal records to wire format (strip internal-only keys)."""

# Keys that are internal bookkeeping and must never be returned on the wire.
_INTERNAL = {"_seq"}


def public(record):
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def public_list(records):
    return [public(r) for r in records]
