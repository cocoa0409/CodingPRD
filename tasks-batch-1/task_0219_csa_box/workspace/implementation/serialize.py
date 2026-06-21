"""Public serialization of entity records.

Strips internal-only keys (those beginning with '_') from the stored record
before returning to the client. Stored records already use the public field
names defined in SCAFFOLD §1.1, so serialization is just a filtered copy.
"""


def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
