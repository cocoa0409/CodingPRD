"""Resource serialization — strips internal fields from response bodies."""

# Internal bookkeeping fields that must never appear in response bodies.
_INTERNAL = {"_seq"}


def view(rec):
    """Return a response-safe copy of a record (drops internal fields)."""
    return {k: v for k, v in rec.items() if k not in _INTERNAL}
