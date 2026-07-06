"""Serialize internal records to API JSON.

Common fields (PRD §2.4): id, created_at, updated_at, version. Datetime fields
are emitted as ISO 8601 UTC with three fractional digits (or null). Internal
bookkeeping keys (prefixed with '_') are dropped.
"""
from timeutil import format_iso8601

# Fields that are datetimes and must be ISO-formatted on output.
_DATETIME_FIELDS = {
    "created_at",
    "updated_at",
    "activated_at",
    "cycle_start_utc",
    "cycle_end_utc",
    "closed_at",
    "recording_ended_at",
    "assets_complete_at",
    "turnaround_due_utc",
    "published_at",
    "scheduled_start_utc",
    "scheduled_end_utc",
    "completed_at",
}


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if key in _DATETIME_FIELDS:
            out[key] = format_iso8601(value)
        else:
            out[key] = value
    return out


def serialize_list(records):
    return [serialize(r) for r in records]
