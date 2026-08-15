"""Entity serializers: convert stored records to API-facing dicts.

Datetimes render as ISO 8601 UTC with 3 fractional digits (PRD 2.4).
"""

import db

DATETIME_FIELDS = {
    "created_at",
    "updated_at",
    "effective_from",
    "effective_to",
    "service_from",
    "service_to",
    "admission_date",
    "discharge_date",
    "determined_at",
    "resolved_at",
    "submitted_at",
    "decided_at",
    "requested_at",
    "due_at",
    "completed_at",
    "finalized_at",
}


def serialize(rec: dict) -> dict:
    out = {}
    for k, v in rec.items():
        if k in DATETIME_FIELDS:
            out[k] = db.fmt_ts(v)
        else:
            out[k] = v
    return out
