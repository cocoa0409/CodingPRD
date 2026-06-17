"""Serialization of internal records to API output dicts.

Records are stored as plain dicts. Datetime fields are stored as aware UTC
datetimes and rendered to ISO 8601 (3 fractional digits) on output. Internal
bookkeeping keys (prefixed with '_') are stripped.
"""
from timeutil import format_iso

# Fields that carry datetime values and must be ISO-rendered on output.
_DATETIME_FIELDS = {
    "created_at", "updated_at",
    "cycle_start_utc", "scheduled_start_utc", "occupancy_end_utc",
    "vehicle_release_utc",
}


def serialize(record):
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        if k in _DATETIME_FIELDS and v is not None:
            out[k] = format_iso(v)
        else:
            out[k] = v
    return out


def serialize_list(records):
    return [serialize(r) for r in records]
