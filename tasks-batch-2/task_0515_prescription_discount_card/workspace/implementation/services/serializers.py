"""Entity -> public JSON dict serializers.

We store records as plain dicts already shaped like the public representation,
so serialization is mostly identity. We return copies to avoid accidental
external mutation and to control field order/inclusion.
"""


def _copy(record):
    return dict(record)


def serialize(record):
    return _copy(record)


def serialize_list(records):
    return [_copy(r) for r in records]
