"""Serialize internal records into API output dicts.

Internal records store datetimes as tz-aware datetime objects and carry private
fields (prefixed with '_'). Serialization converts datetimes to ISO strings and
drops private fields.
"""
import clock

# Public field order per entity (datetime fields listed in DATETIME_FIELDS).
DATETIME_FIELDS = {
    "created_at", "updated_at", "drop_off_at", "ready_by", "ready_at",
    "warranty_expires_at", "picked_up_at",
}


def _serialize(record):
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        if k in DATETIME_FIELDS:
            out[k] = clock.to_iso(v) if v is not None else None
        else:
            out[k] = v
    return out


def public(record):
    return _serialize(record)


def public_list(records):
    return [_serialize(r) for r in records]
