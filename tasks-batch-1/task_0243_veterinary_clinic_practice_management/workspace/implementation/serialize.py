"""Resource -> JSON serialization. Strips internal bookkeeping fields.

The Invoice is immutable and carries only id + created_at (PRD §2.4): it has no
updated_at and no version. All other entities carry the full common set.
"""

_INTERNAL = {"_seq"}


def public(record):
    return {k: v for k, v in record.items() if k not in _INTERNAL}
