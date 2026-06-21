"""Public serialization of records.

Strips internal-only fields (those prefixed with '_') from the stored record
so the API never leaks bookkeeping state. Field names are exactly those
declared in SCAFFOLD §1.1.
"""


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
