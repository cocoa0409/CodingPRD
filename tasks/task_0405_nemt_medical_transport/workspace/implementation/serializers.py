"""Entity -> public JSON representation.

Entities are stored as plain dicts that already match their public shape, so
serialization is mostly a defensive copy. EligibilitySpan and RateSchedule are
immutable append-only records: they carry only id + created_at (no updated_at,
no version) per PRD 2.4.
"""


def serialize(entity):
    return {k: v for k, v in entity.items() if k != "_seq"}


def serialize_list(entities):
    return [serialize(e) for e in entities]
