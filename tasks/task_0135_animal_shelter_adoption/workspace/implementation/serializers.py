"""Output serializers — project each stored record to its API representation.

Records are stored as plain dicts already containing the right fields; serializers
exist to (a) control field order/inclusion and (b) ensure Microchip omits
updated_at/version (immutable registry row, PRD §2.4).
"""

# Fields common to versioned entities, plus their domain fields. We simply return a
# shallow copy of the stored dict; every stored field is an API field. Microchip is
# the only exception and is handled explicitly.


def serialize(record):
    """Default serializer: a shallow copy of the stored record."""
    return dict(record)


def serialize_microchip(record):
    """Microchip carries only id + created_at + domain fields (no updated_at/version)."""
    out = dict(record)
    out.pop("updated_at", None)
    out.pop("version", None)
    return out
