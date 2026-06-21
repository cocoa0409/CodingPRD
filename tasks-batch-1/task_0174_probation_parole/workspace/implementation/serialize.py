"""Resource serialization.

Strips internal bookkeeping fields (those prefixed with '_') from the stored
record before it is returned to the client.
"""


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
