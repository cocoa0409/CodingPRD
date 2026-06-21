"""Public serialization of records.

Strips internal-only keys (those prefixed with '_') and presents the exact
field set declared per entity in SCAFFOLD §1.1. Field ordering is not
significant for JSON consumers; we simply omit internal bookkeeping keys.
"""


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
