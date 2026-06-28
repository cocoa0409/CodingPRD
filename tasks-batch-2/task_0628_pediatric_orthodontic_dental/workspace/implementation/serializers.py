"""Public serializers: strip internal fields (e.g. _seq) from stored records.

Each stored record carries every public field plus internal bookkeeping keys
prefixed with an underscore. Serialization returns a shallow copy with the
underscore-prefixed keys removed.
"""


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
