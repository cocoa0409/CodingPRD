"""Public serialization of entities. Returns exactly the fields each entity
declares in SCAFFOLD §1.1 plus the common fields (id, created_at, updated_at, version).

We store records as plain dicts that already hold all declared fields, so
serialization is a shallow copy. This keeps the public shape stable regardless
of internal bookkeeping (there is no internal-only field on these records).
"""


def serialize(record):
    return dict(record)


def serialize_list(records):
    return [dict(r) for r in records]
