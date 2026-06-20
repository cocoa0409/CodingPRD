"""Serialize stored records to API output shape (strip internal fields)."""

# Internal-only keys never exposed in API output.
_INTERNAL = {"_seq"}


def public(record):
    """Return a copy of the record with internal bookkeeping keys removed."""
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def public_list(records):
    return [public(r) for r in records]
