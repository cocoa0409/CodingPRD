"""Serializers — expose exactly the fields each entity declares (SCAFFOLD §1.1).

Records are stored as plain dicts already shaped with the right field names, so
serialization is a shallow copy. Centralising it keeps internal-only bookkeeping
keys (e.g. interest_paid_cents / principal_paid_cents tracking) out of responses.
"""

# Internal bookkeeping keys that must never appear in API output.
_INTERNAL = {"interest_paid_cents", "principal_paid_cents", "noticed_by_user_id"}


def _clean(record):
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def serialize(record):
    return _clean(record)


def serialize_list(records):
    return [_clean(r) for r in records]
