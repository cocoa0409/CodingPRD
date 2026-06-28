"""Common-field stamping and serialization for all entities (PRD §2.4).

Most resources carry id, created_at, updated_at, version. SensorReading is the
exception: it is an append-only telemetry event carrying only id and created_at
(no updated_at, no version) — created with ``stamp_create_event``.

Datetimes are stored internally as aware UTC objects and ISO-serialized (3
fractional digits) on output. The ``_seq`` and other underscore-prefixed keys
are internal bookkeeping and are stripped from the public view.
"""

from db import store, iso_millis

# Per-entity datetime fields that must be ISO-serialized in output.
_DATETIME_FIELDS = {
    "created_at",
    "updated_at",
    "last_sanitation_at",
}


def stamp_create(record):
    """Assign id + common fields (id, created_at, updated_at, version) on creation."""
    now = store.now()
    record["id"] = store.new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def stamp_create_event(record):
    """Assign id + created_at only (append-only event; no updated_at/version)."""
    now = store.now()
    record["id"] = store.new_id()
    record["created_at"] = now
    record["_seq"] = store.next_seq()
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
