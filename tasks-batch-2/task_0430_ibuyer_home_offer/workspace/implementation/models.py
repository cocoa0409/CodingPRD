"""Common-field stamping and serialization for all entities.

Every resource carries id, created_at, updated_at, version (PRD §2.4). The
internal record stores datetimes; serialization formats them as ISO-8601 UTC
with three fractional digits. Datetime business fields (issued_at, expires_at,
close_date) are likewise stored as aware datetimes and serialized the same way.
"""

from db import store, iso_millis

# Per-entity datetime fields that must be ISO-serialized in output.
_DATETIME_FIELDS = {
    "created_at",
    "updated_at",
    "issued_at",
    "expires_at",
    "close_date",
}


def stamp_create(record):
    """Assign id + common fields on creation, using the logical clock."""
    now = store.now()
    record["id"] = store.new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def touch(record):
    """Bump version and refresh updated_at on a mutation (PRD §2.4)."""
    record["version"] += 1
    record["updated_at"] = store.now()
    return record


def serialize(record):
    """Produce the public JSON view: datetimes -> ISO strings, internal keys hidden."""
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if key in _DATETIME_FIELDS and value is not None:
            out[key] = iso_millis(value)
        else:
            out[key] = value
    return out
