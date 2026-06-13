"""Serializers: project stored records into response shapes with the exact
field set declared per entity in SCAFFOLD §1.1. Records are stored as full dicts
already shaped to these fields, so serialization is mostly identity; we copy to
avoid leaking the internal dict reference."""


def _copy(record):
    return dict(record) if record is not None else None


def chef(r):
    return _copy(r)


def menu(r):
    return _copy(r)


def travel_zone(r):
    return _copy(r)


def availability_block(r):
    return _copy(r)


def client(r):
    return _copy(r)


def booking(r):
    return _copy(r)


def grocery_run(r):
    return _copy(r)


def payment(r):
    return _copy(r)


def recurring_plan(r):
    return _copy(r)


def reschedule_request(r):
    return _copy(r)
