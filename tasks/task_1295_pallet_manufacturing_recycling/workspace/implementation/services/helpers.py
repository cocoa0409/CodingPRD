"""Shared helpers: common-field stamping, serialization (stripping internal
underscore-prefixed bookkeeping fields), existence lookups, sorting."""

from db import db, new_id, stamp_now, now
from errors import raise_err

# Entities that carry the common system fields (created_at/updated_at/version).
# LumberPriceIndex and SeasonalPriceIndex are immutable: id + created_at only.

_CREATION_COUNTER = [0]


def init_common(record):
    """Stamp id/created_at/updated_at/version=1 on a new mutable resource."""
    record["id"] = new_id()
    ts = stamp_now()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_created_sort"] = (now(), _CREATION_COUNTER[0])
    _CREATION_COUNTER[0] += 1
    return record


def init_immutable(record):
    """Market-data rows: id + created_at only; no updated_at/version."""
    record["id"] = new_id()
    record["created_at"] = stamp_now()
    record["_created_sort"] = (now(), _CREATION_COUNTER[0])
    _CREATION_COUNTER[0] += 1
    return record


def touch(record):
    """Bump updated_at and version on a mutation."""
    record["updated_at"] = stamp_now()
    record["version"] += 1


def serialize(record):
    """Public view of a resource: drop internal underscore-prefixed fields."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_list(records):
    return [serialize(r) for r in records]


def sorted_by_creation(records):
    """Default list ordering: creation timestamp ascending."""
    return sorted(records, key=lambda r: r["_created_sort"])


def get_or_404(table, resource_id, label):
    rec = table.get(resource_id)
    if rec is None:
        raise_err("ERR_NOT_FOUND", "%s not found: %s" % (label, resource_id))
    return rec


def ref_or_404(table, resource_id, field_name):
    """Body-referenced FK existence -> ERR_REFERENCED_NOT_FOUND."""
    if resource_id is None:
        return None
    rec = table.get(resource_id)
    if rec is None:
        raise_err(
            "ERR_REFERENCED_NOT_FOUND",
            "Referenced %s does not exist: %s" % (field_name, resource_id),
        )
    return rec
